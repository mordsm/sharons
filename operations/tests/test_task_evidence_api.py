import json

import pytest
from django.utils import timezone

from governance.models import AuditEvent
from operations.models import Evidence, Task
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
def test_task_evidence_endpoint_records_evidence_and_audit_event(client, task):
    response = client.post(
        f"/api/v1/tasks/{task.id}/evidence/",
        data=json.dumps(
            {
                "kind": Evidence.Kind.ARTIFACT,
                "uri_or_reference": "artifact://beta-checklist.md",
                "checksum": "sha256:abc123",
                "metadata": {"criterion": "desktop and mobile covered"},
                "verified": True,
            }
        ),
        content_type="application/json",
        headers={"Idempotency-Key": "evidence-1", "X-Correlation-ID": "corr-evidence-1"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["evidence"]["kind"] == Evidence.Kind.ARTIFACT
    assert body["evidence"]["uri_or_reference"] == "artifact://beta-checklist.md"
    assert body["evidence"]["verified"] is True
    assert Evidence.objects.count() == 1
    assert AuditEvent.objects.filter(
        action="operations.task.evidence_recorded",
        correlation_id="corr-evidence-1",
        metadata__task_id=str(task.id),
    ).exists()


@pytest.mark.django_db
def test_task_evidence_endpoint_is_idempotent(client, task):
    payload = {"kind": Evidence.Kind.TEST, "uri_or_reference": "pytest operations"}
    headers = {"Idempotency-Key": "evidence-2", "X-Correlation-ID": "corr-evidence-2"}

    first = client.post(f"/api/v1/tasks/{task.id}/evidence/", data=json.dumps(payload), content_type="application/json", headers=headers)
    second = client.post(f"/api/v1/tasks/{task.id}/evidence/", data=json.dumps(payload), content_type="application/json", headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()
    assert Evidence.objects.count() == 1
    assert AuditEvent.objects.count() == 1


@pytest.mark.django_db
def test_task_evidence_endpoint_rejects_reused_idempotency_key_with_different_payload(client, task):
    headers = {"Idempotency-Key": "evidence-3", "X-Correlation-ID": "corr-evidence-3"}
    client.post(
        f"/api/v1/tasks/{task.id}/evidence/",
        data=json.dumps({"kind": Evidence.Kind.TEST, "uri_or_reference": "pytest operations"}),
        content_type="application/json",
        headers=headers,
    )

    response = client.post(
        f"/api/v1/tasks/{task.id}/evidence/",
        data=json.dumps({"kind": Evidence.Kind.SOURCE, "uri_or_reference": "docs/cos/TEST_REPORT.md"}),
        content_type="application/json",
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


@pytest.mark.django_db
def test_task_evidence_endpoint_rejects_empty_reference(client, task):
    response = client.post(
        f"/api/v1/tasks/{task.id}/evidence/",
        data=json.dumps({"kind": Evidence.Kind.ARTIFACT, "uri_or_reference": "   "}),
        content_type="application/json",
        headers={"Idempotency-Key": "evidence-4", "X-Correlation-ID": "corr-evidence-4"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_EVIDENCE_PAYLOAD"
    assert Evidence.objects.count() == 0
