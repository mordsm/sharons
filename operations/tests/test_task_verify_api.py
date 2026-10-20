import json

import pytest
from django.utils import timezone

from governance.models import AuditEvent
from operations.models import AcceptanceCriterion, Evidence, Task
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
    task = Task.objects.create(
        objective=active_objective,
        title="Prepare beta checklist",
        business_outcome="Ready for beta",
        status=Task.Status.DELIVERED_UNVERIFIED,
        created_by="test",
    )
    AcceptanceCriterion.objects.create(task=task, description="Verified beta checklist exists.")
    return task


@pytest.mark.django_db
def test_task_verify_endpoint_blocks_without_verified_evidence(client, task):
    response = client.post(
        f"/api/v1/tasks/{task.id}/verify/",
        data=json.dumps({"mark_passed": True}),
        content_type="application/json",
        headers={"Idempotency-Key": "verify-1", "X-Correlation-ID": "corr-verify-1"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TASK_VERIFY_BLOCKED"
    task.refresh_from_db()
    assert task.status == Task.Status.DELIVERED_UNVERIFIED
    assert task.acceptance_criteria.get().status == AcceptanceCriterion.Status.PENDING
    assert AuditEvent.objects.count() == 0


@pytest.mark.django_db
def test_task_verify_endpoint_marks_required_criteria_passed_and_moves_to_verifying(client, task):
    Evidence.objects.create(
        task=task,
        kind=Evidence.Kind.ARTIFACT,
        uri_or_reference="artifact://beta-checklist.md",
        verified=True,
        created_by="qa",
    )

    response = client.post(
        f"/api/v1/tasks/{task.id}/verify/",
        data=json.dumps({"mark_passed": True, "notes": "Checklist evidence reviewed."}),
        content_type="application/json",
        headers={"Idempotency-Key": "verify-2", "X-Correlation-ID": "corr-verify-2", "X-Actor-ID": "qa_agent"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["task"]["status"] == Task.Status.VERIFYING
    assert body["task"]["version"] == 2
    assert body["task"]["acceptance_criteria"][0]["status"] == AcceptanceCriterion.Status.PASSED

    task.refresh_from_db()
    criterion = task.acceptance_criteria.get()
    assert task.status == Task.Status.VERIFYING
    assert criterion.status == AcceptanceCriterion.Status.PASSED
    assert criterion.verified_by == "qa_agent"
    assert criterion.verified_at is not None
    assert AuditEvent.objects.filter(
        action="operations.task.verified",
        correlation_id="corr-verify-2",
        metadata__criteria_marked_passed=1,
    ).exists()


@pytest.mark.django_db
def test_task_verify_endpoint_is_idempotent(client, task):
    Evidence.objects.create(
        task=task,
        kind=Evidence.Kind.TEST,
        uri_or_reference="pytest operations",
        verified=True,
        created_by="qa",
    )
    payload = {"mark_passed": True}
    headers = {"Idempotency-Key": "verify-3", "X-Correlation-ID": "corr-verify-3"}

    first = client.post(f"/api/v1/tasks/{task.id}/verify/", data=json.dumps(payload), content_type="application/json", headers=headers)
    second = client.post(f"/api/v1/tasks/{task.id}/verify/", data=json.dumps(payload), content_type="application/json", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert AuditEvent.objects.count() == 1


@pytest.mark.django_db
def test_task_verify_endpoint_rejects_reused_idempotency_key_with_different_payload(client, task):
    Evidence.objects.create(
        task=task,
        kind=Evidence.Kind.TEST,
        uri_or_reference="pytest operations",
        verified=True,
        created_by="qa",
    )
    headers = {"Idempotency-Key": "verify-4", "X-Correlation-ID": "corr-verify-4"}
    client.post(f"/api/v1/tasks/{task.id}/verify/", data=json.dumps({"mark_passed": True}), content_type="application/json", headers=headers)

    response = client.post(
        f"/api/v1/tasks/{task.id}/verify/",
        data=json.dumps({"mark_passed": False}),
        content_type="application/json",
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
