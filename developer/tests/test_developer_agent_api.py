import json

import pytest

from developer.models import DeveloperWorkContract, ImplementationPlan
from governance.models import AuditEvent
from operations.models import Evidence, Task
from portfolio.models import Objective, Project, ProjectConnection, StrategyVersion


pytestmark = pytest.mark.django_db


def headers(key: str = "developer-1") -> dict:
    return {"Idempotency-Key": key, "X-Correlation-ID": f"corr-{key}", "X-Actor-ID": "developer"}


@pytest.fixture
def active_objective():
    strategy = StrategyVersion.objects.create(version=1, title="90 day plan", content={}, status=StrategyVersion.Status.ACTIVE)
    return Objective.objects.create(
        code="O1",
        strategy_version=strategy,
        name="Mental Trainer commercial readiness",
        business_outcome="Prepare product for beta.",
        status=Objective.Status.ACTIVE,
    )


@pytest.fixture
def in_progress_task(active_objective):
    return Task.objects.create(
        objective=active_objective,
        title="Implement onboarding goal capture",
        status=Task.Status.IN_PROGRESS,
        business_outcome="Beta onboarding captures user goals.",
        created_by="product_manager",
        owner_agent_id="developer",
    )


@pytest.fixture
def project_connection():
    project = Project.objects.create(
        slug="mental-trainer",
        name="Mental Trainer",
        status=Project.Status.ACTIVE,
        owner="chief_of_staff",
        repository_reference="C:\\workspace\\mental_trainer",
    )
    connection = ProjectConnection.objects.create(
        project=project,
        connection_type=ProjectConnection.ConnectionType.REPOSITORY,
        adapter_type="developer_read_only",
        permission_mode=ProjectConnection.PermissionMode.READ_ONLY,
        capabilities={"read": True, "propose": True},
    )
    return project, connection


def contract_payload(task: Task, project: Project, connection: ProjectConnection) -> dict:
    return {
        "task_id": str(task.id),
        "project_id": str(project.id),
        "project_connection_id": connection.id,
        "title": "Onboarding implementation contract",
        "objective": "Implement goal capture without external repository writes.",
        "scope": ["Inspect onboarding flow", "Propose implementation changes"],
        "constraints": {"external_write": False, "deploy": False},
        "acceptance_focus": ["Evidence is recorded for verification."],
    }


def test_developer_work_contract_create_is_internal_only_and_idempotent(client, in_progress_task, project_connection):
    project, connection = project_connection
    payload = contract_payload(in_progress_task, project, connection)

    first = client.post("/api/v1/developer/work-contracts/create/", data=json.dumps(payload), content_type="application/json", headers=headers())
    second = client.post("/api/v1/developer/work-contracts/create/", data=json.dumps(payload), content_type="application/json", headers=headers())

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()
    contract = DeveloperWorkContract.objects.get()
    assert contract.no_repo_write is True
    assert contract.no_deploy is True
    assert contract.project_connection == connection
    assert AuditEvent.objects.filter(action="developer.work_contract.created", object_id=str(contract.id), correlation_id="corr-developer-1").exists()


def test_developer_work_contract_requires_approved_or_active_task(client, active_objective, project_connection):
    project, connection = project_connection
    task = Task.objects.create(objective=active_objective, title="Draft implementation", status=Task.Status.DRAFT, created_by="chief")

    response = client.post(
        "/api/v1/developer/work-contracts/create/",
        data=json.dumps(contract_payload(task, project, connection)),
        content_type="application/json",
        headers=headers("developer-2"),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DEVELOPER_BLOCKED"
    assert DeveloperWorkContract.objects.count() == 0


@pytest.fixture
def developer_contract(in_progress_task, project_connection):
    project, connection = project_connection
    return DeveloperWorkContract.objects.create(
        task=in_progress_task,
        project=project,
        project_connection=connection,
        title="Onboarding implementation contract",
        objective="Implement goal capture.",
        scope=["Propose code changes"],
        created_by="developer",
    )


def test_implementation_plan_create_updates_contract_and_audits(client, developer_contract):
    payload = {
        "title": "Goal capture implementation plan",
        "summary": "Add a first-session goal capture step.",
        "planned_changes": ["Add goal field to onboarding state", "Render goal capture screen"],
        "verification_plan": ["Run onboarding flow test", "Attach screenshot or test output"],
        "risks": ["Existing users may skip onboarding."],
    }

    response = client.post(
        f"/api/v1/developer/work-contracts/{developer_contract.id}/implementation-plans/create/",
        data=json.dumps(payload),
        content_type="application/json",
        headers=headers("developer-plan-1"),
    )

    assert response.status_code == 201
    body = response.json()["implementation_plan"]
    assert body["status"] == ImplementationPlan.Status.NEEDS_REVIEW
    assert body["no_repo_write"] is True
    developer_contract.refresh_from_db()
    assert developer_contract.status == DeveloperWorkContract.Status.IN_PROGRESS
    assert AuditEvent.objects.filter(action="developer.implementation_plan.created", object_id=body["id"]).exists()


@pytest.fixture
def implementation_plan(developer_contract):
    developer_contract.status = DeveloperWorkContract.Status.IN_PROGRESS
    developer_contract.save(update_fields=["status"])
    return ImplementationPlan.objects.create(
        contract=developer_contract,
        title="Goal capture implementation plan",
        summary="Add a first-session goal capture step.",
        planned_changes=["Add goal field"],
        verification_plan=["Run tests"],
        created_by="developer",
    )


def test_implementation_plan_deliver_records_evidence_and_moves_task_to_verification_queue(client, implementation_plan):
    response = client.post(
        f"/api/v1/developer/implementation-plans/{implementation_plan.id}/deliver/",
        data=json.dumps({"evidence": [{"uri_or_reference": "tests/test_onboarding.py::test_goal_capture passed"}]}),
        content_type="application/json",
        headers=headers("developer-deliver-1"),
    )

    assert response.status_code == 200
    implementation_plan.refresh_from_db()
    task = implementation_plan.contract.task
    task.refresh_from_db()
    implementation_plan.contract.refresh_from_db()
    assert implementation_plan.status == ImplementationPlan.Status.DELIVERED_UNVERIFIED
    assert implementation_plan.contract.status == DeveloperWorkContract.Status.DELIVERED
    assert task.status == Task.Status.DELIVERED_UNVERIFIED
    assert Evidence.objects.filter(task=task, verified=False).count() == 1
    assert AuditEvent.objects.filter(action="developer.implementation_plan.delivered", metadata__task_status=Task.Status.DELIVERED_UNVERIFIED).exists()


def test_implementation_plan_deliver_requires_in_progress_task(client, implementation_plan):
    task = implementation_plan.contract.task
    task.status = Task.Status.ASSIGNED
    task.save(update_fields=["status"])

    response = client.post(
        f"/api/v1/developer/implementation-plans/{implementation_plan.id}/deliver/",
        data=json.dumps({"evidence": ["manual evidence"]}),
        content_type="application/json",
        headers=headers("developer-deliver-2"),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DEVELOPER_BLOCKED"


def test_developer_status_reports_internal_boundaries(client, implementation_plan):
    response = client.get(f"/api/v1/developer/status/?project_id={implementation_plan.contract.project_id}")

    assert response.status_code == 200
    status = response.json()["status"]
    assert status["agent_id"] == "developer"
    assert status["repo_write_enabled"] is False
    assert status["deploy_enabled"] is False
    assert status["work_contracts"] == 1
    assert status["implementation_plans"] == 1

