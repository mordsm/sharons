import json

import pytest
from django.utils import timezone

from governance.models import AuditEvent
from operations.models import AgentDefinition, Task
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
def approved_task(active_objective):
    return Task.objects.create(
        objective=active_objective,
        title="Prepare beta checklist",
        business_outcome="Ready for beta",
        status=Task.Status.APPROVED,
        created_by="test",
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
    )


@pytest.mark.django_db
def test_task_assign_endpoint_assigns_available_agent_and_records_audit(client, approved_task, agent):
    response = client.post(
        f"/api/v1/tasks/{approved_task.id}/assign/",
        data=json.dumps({"agent_id": agent.agent_id, "expected_version": 1}),
        content_type="application/json",
        headers={"Idempotency-Key": "assign-1", "X-Correlation-ID": "corr-assign-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["task"]["status"] == Task.Status.ASSIGNED
    assert body["task"]["owner_agent_id"] == "engineering_agent"
    assert body["task"]["version"] == 2

    approved_task.refresh_from_db()
    agent.refresh_from_db()
    assert approved_task.status == Task.Status.ASSIGNED
    assert approved_task.owner_agent_id == "engineering_agent"
    assert agent.current_task_count == 1
    assert AuditEvent.objects.filter(
        action="operations.task.assigned",
        correlation_id="corr-assign-1",
        metadata__agent_id="engineering_agent",
    ).exists()


@pytest.mark.django_db
def test_task_assign_endpoint_rejects_busy_agent(client, approved_task):
    busy_agent = AgentDefinition.objects.create(
        agent_id="busy_agent",
        role="Busy Agent",
        max_concurrent_tasks=1,
        current_task_count=1,
    )

    response = client.post(
        f"/api/v1/tasks/{approved_task.id}/assign/",
        data=json.dumps({"agent_id": busy_agent.agent_id, "expected_version": 1}),
        content_type="application/json",
        headers={"Idempotency-Key": "assign-2", "X-Correlation-ID": "corr-assign-2"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TASK_ASSIGN_BLOCKED"
    approved_task.refresh_from_db()
    busy_agent.refresh_from_db()
    assert approved_task.status == Task.Status.APPROVED
    assert busy_agent.current_task_count == 1


@pytest.mark.django_db
def test_task_assign_endpoint_rejects_unapproved_task(client, active_objective, agent):
    draft_task = Task.objects.create(
        objective=active_objective,
        title="Prepare beta checklist",
        status=Task.Status.DRAFT,
        created_by="test",
    )

    response = client.post(
        f"/api/v1/tasks/{draft_task.id}/assign/",
        data=json.dumps({"agent_id": agent.agent_id, "expected_version": 1}),
        content_type="application/json",
        headers={"Idempotency-Key": "assign-3", "X-Correlation-ID": "corr-assign-3"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TASK_ASSIGN_BLOCKED"
    draft_task.refresh_from_db()
    assert draft_task.status == Task.Status.DRAFT
    assert draft_task.owner_agent_id == ""


@pytest.mark.django_db
def test_task_assign_endpoint_rejects_stale_expected_version(client, approved_task, agent):
    approved_task.version = 2
    approved_task.save()

    response = client.post(
        f"/api/v1/tasks/{approved_task.id}/assign/",
        data=json.dumps({"agent_id": agent.agent_id, "expected_version": 1}),
        content_type="application/json",
        headers={"Idempotency-Key": "assign-4", "X-Correlation-ID": "corr-assign-4"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TASK_VERSION_CONFLICT"


@pytest.mark.django_db
def test_task_assign_endpoint_is_idempotent(client, approved_task, agent):
    payload = {"agent_id": agent.agent_id, "expected_version": 1}
    headers = {"Idempotency-Key": "assign-5", "X-Correlation-ID": "corr-assign-5"}

    first = client.post(f"/api/v1/tasks/{approved_task.id}/assign/", data=json.dumps(payload), content_type="application/json", headers=headers)
    second = client.post(f"/api/v1/tasks/{approved_task.id}/assign/", data=json.dumps(payload), content_type="application/json", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    agent.refresh_from_db()
    assert agent.current_task_count == 1
    assert AuditEvent.objects.count() == 1


@pytest.mark.django_db
def test_task_assign_endpoint_rejects_reused_idempotency_key_with_different_payload(client, approved_task, agent):
    other_agent = AgentDefinition.objects.create(agent_id="other_agent", role="Other Agent")
    headers = {"Idempotency-Key": "assign-6", "X-Correlation-ID": "corr-assign-6"}
    client.post(
        f"/api/v1/tasks/{approved_task.id}/assign/",
        data=json.dumps({"agent_id": agent.agent_id, "expected_version": 1}),
        content_type="application/json",
        headers=headers,
    )

    response = client.post(
        f"/api/v1/tasks/{approved_task.id}/assign/",
        data=json.dumps({"agent_id": other_agent.agent_id, "expected_version": 1}),
        content_type="application/json",
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
