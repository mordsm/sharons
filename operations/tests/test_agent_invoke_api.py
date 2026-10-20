import json

import pytest
from django.utils import timezone

from governance.models import AuditEvent
from operations.models import AgentDefinition, AgentRun, Task
from portfolio.models import Objective, StrategyVersion


@pytest.fixture
def active_objective():
    strategy = StrategyVersion.objects.create(
        version=1,
        title="Initial strategy",
        content={"horizon": "90 days"},
        status=StrategyVersion.Status.ACTIVE,
        valid_from=timezone.now(),
    )
    return Objective.objects.create(
        code="O1",
        strategy_version=strategy,
        name="Mental Trainer commercial readiness",
        business_outcome="Ready for beta",
        status=Objective.Status.ACTIVE,
        owner_agent_id="chief_of_staff",
    )


@pytest.fixture
def agent():
    return AgentDefinition.objects.create(
        agent_id="engineering_agent",
        role="Senior Engineering Agent",
        capabilities=["implementation", "testing"],
        allowed_data_classes=["INTERNAL"],
        max_risk_level=AgentDefinition.RiskLevel.MEDIUM,
        max_concurrent_tasks=2,
        current_task_count=1,
    )


@pytest.fixture
def assigned_task(active_objective, agent):
    return Task.objects.create(
        objective=active_objective,
        title="Prepare beta checklist",
        business_outcome="Ready for beta",
        owner_agent_id=agent.agent_id,
        status=Task.Status.ASSIGNED,
        created_by="test",
    )


@pytest.mark.django_db
def test_agent_invoke_endpoint_creates_started_run_and_audit_event(client, assigned_task, agent):
    response = client.post(
        "/api/v1/agents/invoke/",
        data=json.dumps(
            {
                "task_id": str(assigned_task.id),
                "agent_id": agent.agent_id,
                "input_snapshot": {"task_title": assigned_task.title},
            }
        ),
        content_type="application/json",
        headers={"Idempotency-Key": "invoke-1", "X-Correlation-ID": "corr-invoke-1"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["agent_run"]["agent_id"] == agent.agent_id
    assert body["agent_run"]["task_id"] == str(assigned_task.id)
    assert body["agent_run"]["attempt_number"] == 1
    assert body["agent_run"]["status"] == AgentRun.Status.STARTED
    assert body["agent_run"]["input_snapshot"] == {"task_title": assigned_task.title}
    assert AgentRun.objects.count() == 1
    assert AuditEvent.objects.filter(
        action="operations.agent_run.started",
        correlation_id="corr-invoke-1",
        metadata__no_external_execution=True,
    ).exists()


@pytest.mark.django_db
def test_agent_invoke_endpoint_rejects_task_assigned_to_different_agent(client, assigned_task):
    AgentDefinition.objects.create(agent_id="research_manager", role="Research Manager")

    response = client.post(
        "/api/v1/agents/invoke/",
        data=json.dumps(
            {
                "task_id": str(assigned_task.id),
                "agent_id": "research_manager",
                "input_snapshot": {},
            }
        ),
        content_type="application/json",
        headers={"Idempotency-Key": "invoke-2", "X-Correlation-ID": "corr-invoke-2"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "AGENT_INVOKE_BLOCKED"
    assert AgentRun.objects.count() == 0


@pytest.mark.django_db
def test_agent_invoke_endpoint_rejects_unassigned_task(client, active_objective, agent):
    task = Task.objects.create(
        objective=active_objective,
        title="Prepare beta checklist",
        status=Task.Status.APPROVED,
        created_by="test",
    )

    response = client.post(
        "/api/v1/agents/invoke/",
        data=json.dumps({"task_id": str(task.id), "agent_id": agent.agent_id, "input_snapshot": {}}),
        content_type="application/json",
        headers={"Idempotency-Key": "invoke-3", "X-Correlation-ID": "corr-invoke-3"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "AGENT_INVOKE_BLOCKED"


@pytest.mark.django_db
def test_agent_invoke_endpoint_rejects_third_attempt(client, assigned_task, agent):
    AgentRun.objects.create(task=assigned_task, agent_id=agent.agent_id, attempt_number=1, input_snapshot={}, correlation_id="old-1")
    AgentRun.objects.create(task=assigned_task, agent_id=agent.agent_id, attempt_number=2, input_snapshot={}, correlation_id="old-2")

    response = client.post(
        "/api/v1/agents/invoke/",
        data=json.dumps({"task_id": str(assigned_task.id), "agent_id": agent.agent_id, "input_snapshot": {}}),
        content_type="application/json",
        headers={"Idempotency-Key": "invoke-4", "X-Correlation-ID": "corr-invoke-4"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "AGENT_INVOKE_BLOCKED"
    assert AgentRun.objects.count() == 2


@pytest.mark.django_db
def test_agent_invoke_endpoint_is_idempotent(client, assigned_task, agent):
    payload = {"task_id": str(assigned_task.id), "agent_id": agent.agent_id, "input_snapshot": {"mode": "dry_run"}}
    headers = {"Idempotency-Key": "invoke-5", "X-Correlation-ID": "corr-invoke-5"}

    first = client.post("/api/v1/agents/invoke/", data=json.dumps(payload), content_type="application/json", headers=headers)
    second = client.post("/api/v1/agents/invoke/", data=json.dumps(payload), content_type="application/json", headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()
    assert AgentRun.objects.count() == 1
    assert AuditEvent.objects.count() == 1


@pytest.mark.django_db
def test_agent_invoke_endpoint_rejects_reused_idempotency_key_with_different_payload(client, assigned_task, agent):
    headers = {"Idempotency-Key": "invoke-6", "X-Correlation-ID": "corr-invoke-6"}
    client.post(
        "/api/v1/agents/invoke/",
        data=json.dumps({"task_id": str(assigned_task.id), "agent_id": agent.agent_id, "input_snapshot": {"mode": "a"}}),
        content_type="application/json",
        headers=headers,
    )

    response = client.post(
        "/api/v1/agents/invoke/",
        data=json.dumps({"task_id": str(assigned_task.id), "agent_id": agent.agent_id, "input_snapshot": {"mode": "b"}}),
        content_type="application/json",
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


@pytest.mark.django_db
def test_agent_invoke_endpoint_rejects_invalid_input_snapshot(client, assigned_task, agent):
    response = client.post(
        "/api/v1/agents/invoke/",
        data=json.dumps({"task_id": str(assigned_task.id), "agent_id": agent.agent_id, "input_snapshot": []}),
        content_type="application/json",
        headers={"Idempotency-Key": "invoke-7", "X-Correlation-ID": "corr-invoke-7"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_AGENT_INVOKE_PAYLOAD"
