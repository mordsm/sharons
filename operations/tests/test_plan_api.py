import json

import pytest

from governance.models import AuditEvent
from operations.models import AgentDefinition, AgentRun, Plan, Task
from portfolio.models import Objective, StrategyVersion


pytestmark = pytest.mark.django_db


def active_objective() -> Objective:
    strategy = StrategyVersion.objects.create(
        version=1,
        title="Strategy",
        content={},
        status=StrategyVersion.Status.ACTIVE,
        approved_by="chief_of_staff",
    )
    return Objective.objects.create(
        strategy_version=strategy,
        code="O1",
        name="Mental Trainer readiness",
        business_outcome="Ready for beta.",
        owner_agent_id="product_manager",
        status=Objective.Status.ACTIVE,
    )


def headers(key: str) -> dict:
    return {"Idempotency-Key": key, "X-Correlation-ID": f"corr-{key}", "X-Actor-ID": "chief_of_staff"}


def test_plan_create_api_creates_draft_plan_and_audit_event(client):
    objective = active_objective()
    payload = {
        "objective_id": str(objective.id),
        "name": "Beta readiness plan",
        "assumptions": {"capacity": "protected"},
        "risks": {"manual_qa": "medium"},
    }

    response = client.post("/api/v1/plans/", data=json.dumps(payload), content_type="application/json", headers=headers("plan-create-1"))

    assert response.status_code == 201
    plan = Plan.objects.get(name="Beta readiness plan")
    assert plan.status == Plan.Status.DRAFT
    assert plan.version == 1
    assert AuditEvent.objects.filter(action="operations.plan.created", object_id=str(plan.id)).exists()


def test_plan_create_api_is_idempotent(client):
    objective = active_objective()
    payload = {"objective_id": str(objective.id), "name": "Beta readiness plan"}

    first = client.post("/api/v1/plans/", data=json.dumps(payload), content_type="application/json", headers=headers("plan-create-1"))
    second = client.post("/api/v1/plans/", data=json.dumps(payload), content_type="application/json", headers=headers("plan-create-1"))

    assert first.status_code == 201
    assert second.status_code == 201
    assert Plan.objects.count() == 1


def test_plan_list_and_detail_api(client):
    objective = active_objective()
    plan = Plan.objects.create(
        objective=objective,
        name="Beta readiness plan",
        status=Plan.Status.DRAFT,
        assumptions={"capacity": "protected"},
        risks={"manual_qa": "medium"},
        created_by="chief_of_staff",
    )
    Plan.objects.create(
        objective=objective,
        name="Closed old plan",
        status=Plan.Status.CLOSED,
        created_by="chief_of_staff",
    )

    list_response = client.get("/api/v1/plans/", {"status": Plan.Status.DRAFT})
    detail_response = client.get(f"/api/v1/plans/{plan.id}/")

    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()["plans"]] == [str(plan.id)]
    assert detail_response.status_code == 200
    assert detail_response.json()["plan"]["assumptions"] == {"capacity": "protected"}


def test_plan_list_rejects_invalid_status(client):
    response = client.get("/api/v1/plans/", {"status": "DONEISH"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PLAN_FILTER"


def test_agent_performance_endpoint_returns_run_and_task_counts(client):
    objective = active_objective()
    agent = AgentDefinition.objects.create(
        agent_id="developer",
        role="Developer",
        capabilities=["engineering"],
        allowed_data_classes=["INTERNAL"],
        max_concurrent_tasks=2,
    )
    task = Task.objects.create(
        objective=objective,
        title="Build slice",
        status=Task.Status.ASSIGNED,
        owner_agent_id=agent.agent_id,
        created_by="chief_of_staff",
    )
    AgentRun.objects.create(task=task, agent_id=agent.agent_id, attempt_number=1, status=AgentRun.Status.COMPLETED, input_snapshot={}, correlation_id="corr-run")

    response = client.get(f"/api/v1/agents/{agent.agent_id}/performance/")

    assert response.status_code == 200
    body = response.json()["performance"]
    assert body["agent"]["agent_id"] == "developer"
    assert body["runs"]["completed"] == 1
    assert body["tasks"]["active"] == 1
