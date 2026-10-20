import json

import pytest
from django.utils import timezone

from governance.models import AuditEvent
from operations.models import Task
from portfolio.models import Objective, Project, ProjectConnection, StrategyVersion
from research.models import ResearchTaskContract


pytestmark = pytest.mark.django_db


def headers(key: str) -> dict:
    return {"Idempotency-Key": key, "X-Correlation-ID": "corr-research-contract-1", "X-Actor-ID": "chief_of_staff"}


@pytest.fixture
def active_objective():
    strategy = StrategyVersion.objects.create(version=1, title="Strategy", content={}, status=StrategyVersion.Status.ACTIVE, valid_from=timezone.now())
    return Objective.objects.create(
        code="O1",
        strategy_version=strategy,
        name="Mental Trainer readiness",
        business_outcome="Ready for beta",
        status=Objective.Status.ACTIVE,
        owner_agent_id="chief_of_staff",
    )


@pytest.fixture
def approved_task(active_objective):
    return Task.objects.create(
        objective=active_objective,
        title="Research pricing evidence",
        business_outcome="Evidence-backed pricing decision",
        status=Task.Status.APPROVED,
        created_by="test",
    )


@pytest.fixture
def project_connection():
    project = Project.objects.create(
        slug="research-manager",
        name="Research Manager",
        owner="chief_of_staff",
        status=Project.Status.ACTIVE,
        repository_reference="C:\\workspace\\research_manager",
    )
    connection = ProjectConnection.objects.create(
        project=project,
        connection_type=ProjectConnection.ConnectionType.PRODUCT_API,
        adapter_type="research_manager_read_only",
        capabilities={"contracts": True, "summaries": True},
        permission_mode=ProjectConnection.PermissionMode.READ_ONLY,
    )
    return project, connection


def contract_payload(task: Task, project: Project, connection: ProjectConnection) -> dict:
    return {
        "task_id": str(task.id),
        "project_id": str(project.id),
        "project_connection_id": connection.id,
        "title": "Mental Trainer pricing evidence review",
        "original_request": "Review evidence for pricing and beta readiness.",
        "research_question": "What evidence should shape Mental Trainer beta pricing?",
        "scope": {"domain": "market_research", "allowed_sources": ["internal_records"]},
        "deliverables": ["narrative_synthesis", "limitations"],
        "budgets": {"max_documents": 20, "max_wall_time_minutes": 30},
        "depth_mode": ResearchTaskContract.DepthMode.STANDARD,
    }


def test_research_contract_create_is_idempotent_and_audited(client, approved_task, project_connection):
    project, connection = project_connection
    payload = contract_payload(approved_task, project, connection)

    first = client.post("/api/v1/research/contracts/create/", data=json.dumps(payload), content_type="application/json", headers=headers("research-contract-1"))
    second = client.post("/api/v1/research/contracts/create/", data=json.dumps(payload), content_type="application/json", headers=headers("research-contract-1"))

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()
    contract = ResearchTaskContract.objects.get()
    assert contract.status == ResearchTaskContract.Status.READY
    assert contract.project_connection == connection
    assert AuditEvent.objects.filter(
        action="research.contract.created",
        object_id=str(contract.id),
        metadata__no_external_execution=True,
    ).exists()


def test_research_contract_requires_approved_or_active_task(client, active_objective, project_connection):
    project, connection = project_connection
    task = Task.objects.create(objective=active_objective, title="Draft research task", status=Task.Status.DRAFT, created_by="test")
    payload = contract_payload(task, project, connection)

    response = client.post("/api/v1/research/contracts/create/", data=json.dumps(payload), content_type="application/json", headers=headers("research-contract-2"))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RESEARCH_CONTRACT_BLOCKED"
    assert ResearchTaskContract.objects.count() == 0


def test_research_contract_requires_read_only_connection(client, approved_task):
    project = Project.objects.create(slug="research-manager", name="Research Manager", owner="chief_of_staff")
    connection = ProjectConnection.objects.create(
        project=project,
        connection_type=ProjectConnection.ConnectionType.PRODUCT_API,
        adapter_type="research_manager",
        permission_mode=ProjectConnection.PermissionMode.WRITE_APPROVED,
    )
    payload = contract_payload(approved_task, project, connection)

    response = client.post("/api/v1/research/contracts/create/", data=json.dumps(payload), content_type="application/json", headers=headers("research-contract-3"))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESEARCH_CONTRACT_REFERENCE_NOT_FOUND"
    assert ResearchTaskContract.objects.count() == 0


def test_research_contract_rejects_reused_idempotency_key_with_different_payload(client, approved_task, project_connection):
    project, connection = project_connection
    payload = contract_payload(approved_task, project, connection)
    client.post("/api/v1/research/contracts/create/", data=json.dumps(payload), content_type="application/json", headers=headers("research-contract-4"))
    changed = dict(payload)
    changed["title"] = "Different title"

    response = client.post("/api/v1/research/contracts/create/", data=json.dumps(changed), content_type="application/json", headers=headers("research-contract-4"))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_research_adapter_status_is_read_only_and_does_not_check_external_service(client, project_connection):
    project, connection = project_connection

    response = client.get("/api/v1/research/adapter/status/", {"project_id": str(project.id)})

    assert response.status_code == 200
    status = response.json()["status"]
    assert status["adapter"] == "research_manager_read_only"
    assert status["external_execution_enabled"] is False
    assert status["external_status_checked"] is False
    assert status["projects"][0]["project_id"] == str(project.id)
    assert status["projects"][0]["connections"][0]["id"] == connection.id
