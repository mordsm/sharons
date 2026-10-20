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


@pytest.mark.django_db
def test_intake_creates_draft_task_and_audit_event(client, active_objective):
    response = client.post(
        "/api/v1/cos/intake/",
        data=json.dumps({"objective_id": str(active_objective.id), "title": "Prepare beta checklist"}),
        content_type="application/json",
        headers={"Idempotency-Key": "idem-1", "X-Correlation-ID": "corr-1"},
    )

    assert response.status_code == 201
    body = response.json()
    task = Task.objects.get(id=body["task_id"])
    assert task.status == Task.Status.DRAFT
    assert body["correlation_id"] == "corr-1"
    assert AuditEvent.objects.filter(object_id=str(task.id), correlation_id="corr-1").exists()


@pytest.mark.django_db
def test_intake_rejects_whitespace_title(client, active_objective):
    response = client.post(
        "/api/v1/cos/intake/",
        data=json.dumps({"objective_id": str(active_objective.id), "title": "   "}),
        content_type="application/json",
        headers={"Idempotency-Key": "idem-2", "X-Correlation-ID": "corr-2"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PAYLOAD"
    assert Task.objects.count() == 0


@pytest.mark.django_db
def test_intake_is_idempotent_for_same_payload(client, active_objective):
    payload = {"objective_id": str(active_objective.id), "title": "Prepare launch review"}
    first = client.post(
        "/api/v1/cos/intake/",
        data=json.dumps(payload),
        content_type="application/json",
        headers={"Idempotency-Key": "idem-3", "X-Correlation-ID": "corr-3"},
    )
    second = client.post(
        "/api/v1/cos/intake/",
        data=json.dumps(payload),
        content_type="application/json",
        headers={"Idempotency-Key": "idem-3", "X-Correlation-ID": "corr-3"},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()
    assert Task.objects.count() == 1
    assert AuditEvent.objects.count() == 1


@pytest.mark.django_db
def test_intake_rejects_reused_idempotency_key_with_different_payload(client, active_objective):
    headers = {"Idempotency-Key": "idem-4", "X-Correlation-ID": "corr-4"}
    client.post(
        "/api/v1/cos/intake/",
        data=json.dumps({"objective_id": str(active_objective.id), "title": "First"}),
        content_type="application/json",
        headers=headers,
    )
    response = client.post(
        "/api/v1/cos/intake/",
        data=json.dumps({"objective_id": str(active_objective.id), "title": "Second"}),
        content_type="application/json",
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


@pytest.mark.django_db
def test_intake_rejects_missing_correlation_header(client, active_objective):
    response = client.post(
        "/api/v1/cos/intake/",
        data=json.dumps({"objective_id": str(active_objective.id), "title": "Prepare launch review"}),
        content_type="application/json",
        headers={"Idempotency-Key": "idem-5"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MISSING_REQUIRED_HEADER"


@pytest.mark.django_db
def test_intake_rejects_inactive_objective(client, active_objective):
    active_objective.status = Objective.Status.PAUSED
    active_objective.save()

    response = client.post(
        "/api/v1/cos/intake/",
        data=json.dumps({"objective_id": str(active_objective.id), "title": "Prepare launch review"}),
        content_type="application/json",
        headers={"Idempotency-Key": "idem-6", "X-Correlation-ID": "corr-6"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "OBJECTIVE_NOT_FOUND"
