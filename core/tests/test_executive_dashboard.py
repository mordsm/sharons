from datetime import date

import pytest
from django.utils import timezone

from developer.models import DeveloperWorkContract, ImplementationPlan
from executive_assistant.models import ExecutiveBrief
from finance.models import FinancialRecord
from governance.models import ApprovalRequest, AuditEvent, RuleEngineRun, RuleEngineWorkItem
from operations.models import AgentDefinition, Task
from portfolio.models import Objective, Project, ProjectConnection, StrategyVersion
from product.models import ProductSpecContract, ProductSpecDraft
from project_manager.models import ExecutionReview
from qa.models import VerificationReview


@pytest.fixture
def dashboard_user(django_user_model):
    return django_user_model.objects.create_user(username="ceo", password="secret")


@pytest.fixture
def strategy():
    return StrategyVersion.objects.create(version=1, title="90 day plan", content={}, status=StrategyVersion.Status.ACTIVE)


@pytest.fixture
def objective(strategy):
    return Objective.objects.create(
        code="O1",
        strategy_version=strategy,
        name="Mental Trainer readiness",
        business_outcome="Commercial readiness",
        status=Objective.Status.ACTIVE,
    )


@pytest.mark.django_db
def test_executive_dashboard_requires_login(client):
    response = client.get("/")

    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


@pytest.mark.django_db
def test_executive_dashboard_renders_operational_overview(client, dashboard_user, objective):
    Task.objects.create(
        objective=objective,
        title="Fix onboarding blocker",
        status=Task.Status.BLOCKED,
        created_by="chief_of_staff",
    )
    Task.objects.create(
        objective=objective,
        title="Verify desktop beta",
        status=Task.Status.DELIVERED_UNVERIFIED,
        created_by="chief_of_staff",
    )
    AgentDefinition.objects.create(
        agent_id="qa-agent",
        role="QA",
        capabilities=["verification"],
        allowed_data_classes=["INTERNAL"],
        max_concurrent_tasks=2,
        current_task_count=1,
    )
    ApprovalRequest.objects.create(
        subject_type="operations.Task",
        subject_id="task-1",
        subject_version=1,
        action="operations.task.transition",
        action_payload={"to_status": "APPROVED"},
        action_payload_hash="hash",
        requested_by="chief_of_staff",
        expires_at=timezone.now() + timezone.timedelta(days=1),
    )
    AuditEvent.objects.create(
        actor_type=AuditEvent.ActorType.SYSTEM,
        actor_id="chief_of_staff",
        action="operations.task.blocked",
        object_type="operations.Task",
        object_id="task-1",
        correlation_id="corr-dashboard",
    )

    client.force_login(dashboard_user)
    response = client.get("/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "Executive Overview" in content
    assert "Mental Trainer readiness" in content
    assert "Fix onboarding blocker" in content
    assert "Verify desktop beta" in content
    assert "operations.task.transition" in content
    assert "qa-agent" in content
    assert "operations.task.blocked" in content


@pytest.mark.django_db
def test_executive_dashboard_renders_agent_queue_cockpit(client, dashboard_user, objective):
    AgentDefinition.objects.create(agent_id="chief_of_staff", role="Chief of Staff", active=True)
    AgentDefinition.objects.create(agent_id="product_manager", role="Product Manager", active=True)
    AgentDefinition.objects.create(agent_id="developer", role="Developer", active=True)
    Task.objects.create(
        objective=objective,
        title="Verify shipped artifact",
        status=Task.Status.DELIVERED_UNVERIFIED,
        created_by="developer",
    )
    run = RuleEngineRun.objects.create(
        source="gmail_mock",
        external_event_id="queue-cockpit-1",
        event_type="inbound_email.route",
        event_payload={},
        dry_run=True,
        final_decision="require_approval",
        risk_level="high",
        raw_result={},
    )
    RuleEngineWorkItem.objects.create(
        run=run,
        item_type="ROUTE_REVIEW",
        title="Owner review",
        component="owner_review",
        status=RuleEngineWorkItem.Status.ASSIGNED,
        owner_agent_id="chief_of_staff",
    )

    client.force_login(dashboard_user)
    response = client.get("/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "Agent Queues" in content
    assert "Chief of Staff" in content
    assert "Product Manager" in content
    assert "Executive Assistant" in content
    assert "Finance" in content
    assert "Developer" in content
    assert "Project Manager" in content
    assert "QA" in content
    assert "Rule Work" in content
    assert "Verify" in content


@pytest.mark.django_db
def test_executive_dashboard_renders_chief_of_staff_rule_engine_work(client, dashboard_user):
    run = RuleEngineRun.objects.create(
        source="gmail_mock",
        external_event_id="owner-review-dashboard-1",
        event_type="inbound_email.route",
        event_payload={},
        dry_run=True,
        final_decision="require_approval",
        risk_level="high",
        reason_codes=["SENSITIVE_EMAIL_REQUIRES_HUMAN_REVIEW"],
        raw_result={},
    )
    RuleEngineWorkItem.objects.create(
        run=run,
        item_type="ROUTE_REVIEW",
        title="Review sensitive inbound email",
        component="owner_review",
        purpose="review_sensitive_email",
        status=RuleEngineWorkItem.Status.ASSIGNED,
        owner_agent_id="chief_of_staff",
    )

    client.force_login(dashboard_user)
    response = client.get("/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "Chief of Staff Rule Work" in content
    assert "Review sensitive inbound email" in content
    assert "owner-review-dashboard-1" in content


@pytest.mark.django_db
def test_executive_dashboard_can_complete_chief_of_staff_rule_engine_work(client, dashboard_user):
    run = RuleEngineRun.objects.create(
        source="gmail_mock",
        external_event_id="owner-review-dashboard-2",
        event_type="inbound_email.route",
        event_payload={},
        dry_run=True,
        final_decision="require_approval",
        risk_level="high",
        reason_codes=["SENSITIVE_EMAIL_REQUIRES_HUMAN_REVIEW"],
        raw_result={},
    )
    item = RuleEngineWorkItem.objects.create(
        run=run,
        item_type="ROUTE_REVIEW",
        title="Review sensitive inbound email",
        component="owner_review",
        purpose="review_sensitive_email",
        status=RuleEngineWorkItem.Status.ASSIGNED,
        owner_agent_id="chief_of_staff",
    )

    client.force_login(dashboard_user)
    response = client.post("/", {"action": "complete_rule_engine_work_item", "item_id": str(item.id)})

    assert response.status_code == 302
    item.refresh_from_db()
    assert item.status == RuleEngineWorkItem.Status.COMPLETED
    assert AuditEvent.objects.filter(
        action="governance.rules_engine.work_item.updated",
        actor_id="ceo",
        object_id=str(item.id),
    ).exists()


@pytest.mark.django_db
def test_executive_dashboard_can_create_next_product_draft(client, dashboard_user, objective):
    task = Task.objects.create(
        objective=objective,
        title="Define onboarding PRD",
        status=Task.Status.APPROVED,
        created_by="chief_of_staff",
    )
    project = Project.objects.create(
        slug="mental-trainer",
        name="Mental Trainer",
        status=Project.Status.ACTIVE,
        owner="chief_of_staff",
    )
    connection = ProjectConnection.objects.create(
        project=project,
        connection_type=ProjectConnection.ConnectionType.REPOSITORY,
        adapter_type="product_manager_read_only",
        permission_mode=ProjectConnection.PermissionMode.READ_ONLY,
        capabilities={"spec_contracts": True},
    )
    contract = ProductSpecContract.objects.create(
        task=task,
        project=project,
        project_connection=connection,
        title="Onboarding PRD",
        objective="Define onboarding.",
        problem_statement="Users need first-session guidance.",
        requirements=[{"id": "REQ-1", "text": "Capture first-session goal."}],
        created_by="chief_of_staff",
    )

    client.force_login(dashboard_user)
    response = client.post("/", {"action": "create_next_product_draft"})

    assert response.status_code == 302
    draft = ProductSpecDraft.objects.get(contract=contract)
    assert draft.review_status == ProductSpecDraft.ReviewStatus.NEEDS_REVIEW
    contract.refresh_from_db()
    assert contract.status == ProductSpecContract.Status.IN_PROGRESS
    assert AuditEvent.objects.filter(
        action="product.spec_draft.created",
        actor_id="ceo",
        object_id=str(draft.id),
    ).exists()


@pytest.mark.django_db
def test_executive_dashboard_can_create_next_developer_plan(client, dashboard_user, objective):
    task = Task.objects.create(
        objective=objective,
        title="Implement onboarding goal capture",
        status=Task.Status.IN_PROGRESS,
        created_by="product_manager",
        owner_agent_id="developer",
    )
    project = Project.objects.create(
        slug="mental-trainer-dev",
        name="Mental Trainer Dev",
        status=Project.Status.ACTIVE,
        owner="chief_of_staff",
    )
    connection = ProjectConnection.objects.create(
        project=project,
        connection_type=ProjectConnection.ConnectionType.REPOSITORY,
        adapter_type="developer_read_only",
        permission_mode=ProjectConnection.PermissionMode.READ_ONLY,
        capabilities={"read": True},
    )
    contract = DeveloperWorkContract.objects.create(
        task=task,
        project=project,
        project_connection=connection,
        title="Onboarding implementation contract",
        objective="Implement goal capture.",
        scope=["Add goal field"],
        acceptance_focus=["Run onboarding tests"],
        created_by="developer",
    )

    client.force_login(dashboard_user)
    response = client.post("/", {"action": "create_next_developer_plan"})

    assert response.status_code == 302
    plan = ImplementationPlan.objects.get(contract=contract)
    assert plan.status == ImplementationPlan.Status.NEEDS_REVIEW
    contract.refresh_from_db()
    assert contract.status == DeveloperWorkContract.Status.IN_PROGRESS
    assert AuditEvent.objects.filter(
        action="developer.implementation_plan.created",
        actor_id="ceo",
        object_id=str(plan.id),
    ).exists()


@pytest.mark.django_db
def test_executive_dashboard_can_create_next_execution_review(client, dashboard_user, objective):
    Task.objects.create(
        objective=objective,
        title="Blocked launch task",
        status=Task.Status.BLOCKED,
        created_by="project_manager",
    )

    client.force_login(dashboard_user)
    response = client.post("/", {"action": "create_next_execution_review"})

    assert response.status_code == 302
    review = ExecutionReview.objects.get(objective=objective)
    assert review.status == ExecutionReview.Status.READY
    assert review.no_external_action is True
    assert "O1" in review.summary
    assert AuditEvent.objects.filter(
        action="project_manager.execution_review.created",
        actor_id="ceo",
        object_id=str(review.id),
    ).exists()


@pytest.mark.django_db
def test_executive_dashboard_can_create_next_qa_review_without_accepting_task(client, dashboard_user, objective):
    task = Task.objects.create(
        objective=objective,
        title="Verify delivered artifact",
        status=Task.Status.DELIVERED_UNVERIFIED,
        created_by="developer",
        owner_agent_id="qa",
    )

    client.force_login(dashboard_user)
    response = client.post("/", {"action": "create_next_qa_review"})

    assert response.status_code == 302
    review = VerificationReview.objects.get(task=task)
    assert review.decision == VerificationReview.Decision.NEEDS_MORE_EVIDENCE
    assert review.no_external_action is True
    task.refresh_from_db()
    assert task.status == Task.Status.DELIVERED_UNVERIFIED
    assert AuditEvent.objects.filter(
        action="qa.verification_review.created",
        actor_id="ceo",
        object_id=str(review.id),
    ).exists()


@pytest.mark.django_db
def test_executive_dashboard_can_create_next_executive_assistant_brief(client, dashboard_user, objective):
    Task.objects.create(
        objective=objective,
        title="Resolve operating follow-up",
        status=Task.Status.BLOCKED,
        created_by="chief_of_staff",
    )

    client.force_login(dashboard_user)
    response = client.post("/", {"action": "create_next_executive_brief"})

    assert response.status_code == 302
    brief = ExecutiveBrief.objects.get(title="Cockpit Executive Brief")
    assert brief.status == ExecutiveBrief.Status.READY
    assert brief.no_external_send is True
    assert brief.source_window == {"source": "executive_dashboard"}
    assert AuditEvent.objects.filter(
        action="executive_assistant.brief.created",
        actor_id="ceo",
        object_id=str(brief.id),
    ).exists()


@pytest.mark.django_db
def test_executive_dashboard_can_open_next_finance_review(client, dashboard_user):
    record = FinancialRecord.objects.create(
        record_type=FinancialRecord.RecordType.EXPENSE,
        occurred_on=date(2026, 9, 29),
        amount="49.00",
        currency="USD",
        source="manual",
        category="software",
        description="API subscription",
        external_reference="cockpit-finance-1",
        created_by="finance_agent",
    )

    client.force_login(dashboard_user)
    response = client.post("/", {"action": "open_next_finance_review"})

    assert response.status_code == 302
    record.refresh_from_db()
    assert record.reconciliation_status == FinancialRecord.ReconciliationStatus.NEEDS_REVIEW
    assert record.reconciliation_notes == "Opened from Executive Overview cockpit for finance review."
    assert AuditEvent.objects.filter(
        action="finance.record.reconciled",
        actor_id="ceo",
        object_id=str(record.id),
    ).exists()
