import pytest

from governance.models import AuditEvent
from operations.models import AcceptanceCriterion, AgentDefinition, AgentRun, Evidence, Task
from portfolio.models import Objective, StrategyVersion


@pytest.fixture
def dashboard_user(django_user_model):
    return django_user_model.objects.create_user(username="ops", password="secret")


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


@pytest.fixture
def task(objective):
    task = Task.objects.create(
        objective=objective,
        title="Verify payment readiness",
        business_outcome="Paid beta can start safely",
        owner_agent_id="qa-agent",
        status=Task.Status.DELIVERED_UNVERIFIED,
        created_by="chief_of_staff",
    )
    AcceptanceCriterion.objects.create(task=task, description="Evidence is attached", status=AcceptanceCriterion.Status.PENDING)
    Evidence.objects.create(task=task, kind=Evidence.Kind.TEST, uri_or_reference="pytest operations", verified=True, created_by="qa-agent")
    AgentRun.objects.create(task=task, agent_id="qa-agent", attempt_number=1, input_snapshot={}, correlation_id="corr-run")
    AuditEvent.objects.create(
        actor_type=AuditEvent.ActorType.SYSTEM,
        actor_id="chief_of_staff",
        action="operations.task.evidence_recorded",
        object_type="operations.Task",
        object_id=str(task.id),
        correlation_id="corr-task",
    )
    return task


@pytest.mark.django_db
def test_task_list_requires_login(client):
    response = client.get("/api/v1/tasks/")

    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


@pytest.mark.django_db
def test_task_list_renders_tasks_and_filters(client, dashboard_user, task):
    client.force_login(dashboard_user)
    response = client.get("/api/v1/tasks/", {"status": Task.Status.DELIVERED_UNVERIFIED})

    assert response.status_code == 200
    content = response.content.decode()
    assert "Verify payment readiness" in content
    assert "Mental Trainer readiness" in content
    assert "DELIVERED_UNVERIFIED" in content
    assert "qa-agent" in content


@pytest.mark.django_db
def test_task_detail_renders_operating_record(client, dashboard_user, task):
    client.force_login(dashboard_user)
    response = client.get(f"/api/v1/tasks/{task.id}/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "Verify payment readiness" in content
    assert "Evidence is attached" in content
    assert "pytest operations" in content
    assert "qa-agent" in content
    assert "operations.task.evidence_recorded" in content


@pytest.mark.django_db
def test_task_detail_transition_form_updates_task(client, dashboard_user, objective):
    task = Task.objects.create(objective=objective, title="Plan launch", status=Task.Status.DRAFT, created_by="chief_of_staff")

    client.force_login(dashboard_user)
    response = client.post(
        f"/api/v1/tasks/{task.id}/",
        {
            "action": "transition",
            "idempotency_key": "dashboard-transition-1",
            "to_status": Task.Status.PLANNED,
            "expected_version": task.version,
        },
    )

    assert response.status_code == 302
    task.refresh_from_db()
    assert task.status == Task.Status.PLANNED
    assert task.version == 2
    assert AuditEvent.objects.filter(action="operations.task.transitioned", object_id=str(task.id)).exists()


@pytest.mark.django_db
def test_task_detail_assign_form_assigns_agent(client, dashboard_user, objective):
    task = Task.objects.create(objective=objective, title="Assign launch", status=Task.Status.APPROVED, created_by="chief_of_staff")
    AgentDefinition.objects.create(
        agent_id="ops-agent",
        role="Operations",
        capabilities=["task_execution"],
        allowed_data_classes=["INTERNAL"],
        max_concurrent_tasks=2,
    )

    client.force_login(dashboard_user)
    response = client.post(
        f"/api/v1/tasks/{task.id}/",
        {
            "action": "assign",
            "idempotency_key": "dashboard-assign-1",
            "agent_id": "ops-agent",
            "expected_version": task.version,
        },
    )

    assert response.status_code == 302
    task.refresh_from_db()
    assert task.owner_agent_id == "ops-agent"
    assert task.status == Task.Status.ASSIGNED
    assert AgentDefinition.objects.get(agent_id="ops-agent").current_task_count == 1


@pytest.mark.django_db
def test_task_detail_evidence_form_records_evidence(client, dashboard_user, objective):
    task = Task.objects.create(objective=objective, title="Attach proof", status=Task.Status.IN_PROGRESS, created_by="chief_of_staff")

    client.force_login(dashboard_user)
    response = client.post(
        f"/api/v1/tasks/{task.id}/",
        {
            "action": "evidence",
            "idempotency_key": "dashboard-evidence-1",
            "kind": Evidence.Kind.TEST,
            "uri_or_reference": "pytest operations",
            "checksum": "",
            "verified": "on",
        },
    )

    assert response.status_code == 302
    evidence = task.evidence.get()
    assert evidence.uri_or_reference == "pytest operations"
    assert evidence.verified is True


@pytest.mark.django_db
def test_task_detail_verify_form_verifies_task(client, dashboard_user, task):
    client.force_login(dashboard_user)
    response = client.post(
        f"/api/v1/tasks/{task.id}/",
        {
            "action": "verify",
            "idempotency_key": "dashboard-verify-1",
            "mark_passed": "on",
            "notes": "Looks good.",
        },
    )

    assert response.status_code == 302
    task.refresh_from_db()
    assert task.status == Task.Status.VERIFYING
    assert task.acceptance_criteria.filter(status=AcceptanceCriterion.Status.PASSED).count() == 1
    assert AuditEvent.objects.filter(action="operations.task.verified", object_id=str(task.id)).exists()
