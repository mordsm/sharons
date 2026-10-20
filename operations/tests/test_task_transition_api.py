import json

import pytest
from django.utils import timezone

from governance.models import AuditEvent
from operations.models import Task
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
def task(active_objective):
    return Task.objects.create(
        objective=active_objective,
        title="Prepare beta checklist",
        business_outcome="Ready for beta",
        created_by="test",
    )


@pytest.mark.django_db
def test_task_transition_endpoint_updates_status_and_records_audit(client, task):
    response = client.post(
        f"/api/v1/tasks/{task.id}/transition/",
        data=json.dumps({"to_status": Task.Status.PLANNED, "expected_version": 1}),
        content_type="application/json",
        headers={"Idempotency-Key": "task-transition-1", "X-Correlation-ID": "corr-task-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == Task.Status.PLANNED
    assert body["version"] == 2

    task.refresh_from_db()
    assert task.status == Task.Status.PLANNED
    assert task.version == 2
    assert AuditEvent.objects.filter(
        object_id=str(task.id),
        action="operations.task.transitioned",
        correlation_id="corr-task-1",
    ).exists()


@pytest.mark.django_db
def test_task_transition_endpoint_is_idempotent_for_same_payload(client, task):
    payload = {"to_status": Task.Status.PLANNED, "expected_version": 1}
    headers = {"Idempotency-Key": "task-transition-2", "X-Correlation-ID": "corr-task-2"}

    first = client.post(
        f"/api/v1/tasks/{task.id}/transition/",
        data=json.dumps(payload),
        content_type="application/json",
        headers=headers,
    )
    second = client.post(
        f"/api/v1/tasks/{task.id}/transition/",
        data=json.dumps(payload),
        content_type="application/json",
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert AuditEvent.objects.count() == 1


@pytest.mark.django_db
def test_task_transition_endpoint_rejects_reused_idempotency_key_with_different_payload(client, task):
    headers = {"Idempotency-Key": "task-transition-3", "X-Correlation-ID": "corr-task-3"}
    client.post(
        f"/api/v1/tasks/{task.id}/transition/",
        data=json.dumps({"to_status": Task.Status.PLANNED, "expected_version": 1}),
        content_type="application/json",
        headers=headers,
    )
    response = client.post(
        f"/api/v1/tasks/{task.id}/transition/",
        data=json.dumps({"to_status": Task.Status.CANCELLED, "expected_version": 1}),
        content_type="application/json",
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


@pytest.mark.django_db
def test_task_transition_endpoint_rejects_forbidden_transition(client, task):
    response = client.post(
        f"/api/v1/tasks/{task.id}/transition/",
        data=json.dumps({"to_status": Task.Status.COMPLETED, "expected_version": 1}),
        content_type="application/json",
        headers={"Idempotency-Key": "task-transition-4", "X-Correlation-ID": "corr-task-4"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_TASK_TRANSITION"
    task.refresh_from_db()
    assert task.status == Task.Status.DRAFT


@pytest.mark.django_db
def test_task_transition_endpoint_rejects_stale_expected_version(client, task):
    task.version = 2
    task.save()

    response = client.post(
        f"/api/v1/tasks/{task.id}/transition/",
        data=json.dumps({"to_status": Task.Status.PLANNED, "expected_version": 1}),
        content_type="application/json",
        headers={"Idempotency-Key": "task-transition-5", "X-Correlation-ID": "corr-task-5"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TASK_VERSION_CONFLICT"


@pytest.mark.django_db
def test_task_transition_endpoint_rejects_completion_without_verification(client, task):
    task.status = Task.Status.VERIFYING
    task.save()

    response = client.post(
        f"/api/v1/tasks/{task.id}/transition/",
        data=json.dumps({"to_status": Task.Status.COMPLETED, "expected_version": 1}),
        content_type="application/json",
        headers={"Idempotency-Key": "task-transition-6", "X-Correlation-ID": "corr-task-6"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TASK_VERIFICATION_INCOMPLETE"
    task.refresh_from_db()
    assert task.status == Task.Status.VERIFYING


@pytest.mark.django_db
def test_task_transition_endpoint_rejects_missing_headers(client, task):
    response = client.post(
        f"/api/v1/tasks/{task.id}/transition/",
        data=json.dumps({"to_status": Task.Status.PLANNED, "expected_version": 1}),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_TASK_TRANSITION_PAYLOAD"
