import json

import pytest

from executive_assistant.models import ExecutiveBrief
from operations.models import AgentDefinition, AgentRun, Evidence, Task
from portfolio.models import Objective, StrategyVersion
from project_manager.models import ExecutionReview


pytestmark = pytest.mark.django_db


def headers(key: str) -> dict:
    return {"Idempotency-Key": key, "X-Correlation-ID": f"corr-{key}", "X-Actor-ID": "chief_of_staff"}


@pytest.fixture
def assigned_task():
    strategy = StrategyVersion.objects.create(version=1, title="90 day plan", content={}, status=StrategyVersion.Status.ACTIVE)
    objective = Objective.objects.create(
        code="O1",
        strategy_version=strategy,
        name="Commercial readiness",
        business_outcome="Beta is ready.",
        status=Objective.Status.ACTIVE,
    )
    return Task.objects.create(
        objective=objective,
        title="Prepare the weekly coordination brief",
        status=Task.Status.ASSIGNED,
        owner_agent_id="executive_assistant",
        created_by="chief_of_staff",
    )


def test_runner_delivers_internal_work_for_the_three_operating_agents(client, assigned_task):
    for agent_id in ("product_manager", "project_manager", "executive_assistant"):
        AgentDefinition.objects.create(agent_id=agent_id, role=agent_id, active=True)
    product_task = Task.objects.create(
        objective=assigned_task.objective,
        title="Report product status",
        status=Task.Status.ASSIGNED,
        owner_agent_id="product_manager",
        created_by="chief_of_staff",
    )
    product_response = client.post(
        "/api/v1/agents/execute/",
        data=json.dumps({"task_id": str(product_task.id), "agent_id": "product_manager", "input_snapshot": {}}),
        content_type="application/json",
        headers=headers("run-product"),
    )
    assert product_response.status_code == 200
    assert product_response.json()["agent_run"]["output"]["action"] == "product_status"
    product_task.refresh_from_db()
    assert product_task.status == Task.Status.DELIVERED_UNVERIFIED

    assigned_task.owner_agent_id = "project_manager"
    assigned_task.save(update_fields=["owner_agent_id"])

    response = client.post(
        "/api/v1/agents/execute/",
        data=json.dumps({"task_id": str(assigned_task.id), "agent_id": "project_manager", "input_snapshot": {}}),
        content_type="application/json",
        headers=headers("run-pm"),
    )

    assert response.status_code == 200
    body = response.json()["agent_run"]
    assert body["status"] == AgentRun.Status.COMPLETED
    assert body["output"]["external_action"] is False
    assigned_task.refresh_from_db()
    assert assigned_task.status == Task.Status.DELIVERED_UNVERIFIED
    assert ExecutionReview.objects.filter(objective=assigned_task.objective).exists()
    assert Evidence.objects.filter(task=assigned_task, kind=Evidence.Kind.ARTIFACT).exists()


def test_runner_creates_a_marketing_draft_without_publishing(client, assigned_task):
    from marketing.models import MarketingRequest

    AgentDefinition.objects.create(agent_id="marketing", role="Marketing", active=True)
    assigned_task.owner_agent_id = "marketing"
    assigned_task.title = "Draft the Israel launch plan without publishing"
    assigned_task.save(update_fields=["owner_agent_id", "title"])

    response = client.post(
        "/api/v1/agents/execute/",
        data=json.dumps(
            {
                "task_id": str(assigned_task.id),
                "agent_id": "marketing",
                "input_snapshot": {"geography": ["Israel"], "currency": "ILS", "time_horizon": "30 days"},
            }
        ),
        content_type="application/json",
        headers=headers("run-marketing"),
    )

    assert response.status_code == 200
    output = response.json()["agent_run"]["output"]
    assert output["action"] == "marketing_plan"
    assert output["social_publish_enabled"] is False
    assert output["ad_spend_enabled"] is False
    marketing_request = MarketingRequest.objects.get(id=output["marketing_request_id"])
    assert marketing_request.social_publish_enabled is False
    assert marketing_request.geography == ["Israel"]
    assigned_task.refresh_from_db()
    assert assigned_task.status == Task.Status.DELIVERED_UNVERIFIED


def test_runner_creates_an_executive_brief_without_sending(client, assigned_task):
    AgentDefinition.objects.create(agent_id="executive_assistant", role="Executive Assistant", active=True)

    response = client.post(
        "/api/v1/agents/execute/",
        data=json.dumps({"task_id": str(assigned_task.id), "agent_id": "executive_assistant", "input_snapshot": {}}),
        content_type="application/json",
        headers=headers("run-ea"),
    )

    assert response.status_code == 200
    brief = ExecutiveBrief.objects.get()
    assert brief.no_external_send is True
    assert response.json()["agent_run"]["output"]["brief_id"] == str(brief.id)


def test_runner_marks_unknown_agent_failed(client, assigned_task):
    AgentDefinition.objects.create(agent_id="developer", role="Developer", active=True)
    assigned_task.owner_agent_id = "developer"
    assigned_task.save(update_fields=["owner_agent_id"])

    response = client.post(
        "/api/v1/agents/execute/",
        data=json.dumps({"task_id": str(assigned_task.id), "agent_id": "developer", "input_snapshot": {}}),
        content_type="application/json",
        headers=headers("run-developer"),
    )

    assert response.status_code == 409
    run = AgentRun.objects.get()
    assert run.status == AgentRun.Status.FAILED
    assigned_task.refresh_from_db()
    assert assigned_task.status == Task.Status.ASSIGNED
