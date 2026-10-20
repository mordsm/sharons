import json

import pytest
from django.utils import timezone

from governance.models import ApprovalRequest
from governance.services import create_approval_request


def create_pending_approval(**overrides):
    defaults = {
        "subject_type": "operations.Task",
        "subject_id": "task-api-1",
        "subject_version": 1,
        "action": "operations.task.complete",
        "action_payload": {"status": "COMPLETED"},
        "requested_by": "chief_of_staff",
        "correlation_id": "corr-api-request",
        "expires_at": timezone.now() + timezone.timedelta(hours=1),
    }
    defaults.update(overrides)
    return create_approval_request(**defaults)


@pytest.mark.django_db
def test_approvals_list_returns_existing_approval_requests(client):
    approval = create_pending_approval()

    response = client.get("/api/v1/approvals/")

    assert response.status_code == 200
    approvals = response.json()["approvals"]
    assert len(approvals) == 1
    assert approvals[0]["id"] == str(approval.id)
    assert approvals[0]["status"] == ApprovalRequest.Status.PENDING


@pytest.mark.django_db
def test_approvals_list_filters_by_status(client):
    create_pending_approval(subject_id="pending-task")
    rejected = create_pending_approval(subject_id="rejected-task")
    rejected.status = ApprovalRequest.Status.REJECTED
    rejected.save(update_fields=["status"])

    response = client.get("/api/v1/approvals/?status=REJECTED")

    assert response.status_code == 200
    approvals = response.json()["approvals"]
    assert len(approvals) == 1
    assert approvals[0]["subject_id"] == "rejected-task"


@pytest.mark.django_db
def test_approval_decision_endpoint_approves_bound_action(client):
    approval = create_pending_approval()

    response = client.post(
        f"/api/v1/approvals/{approval.id}/decision/",
        data=json.dumps(
            {
                "decision": ApprovalRequest.Status.APPROVED,
                "subject_version": 1,
                "action_payload": {"status": "COMPLETED"},
            }
        ),
        content_type="application/json",
        headers={"Idempotency-Key": "approval-decision-1", "X-Correlation-ID": "corr-api-decision", "X-Actor-ID": "ceo"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["approval"]["status"] == ApprovalRequest.Status.APPROVED
    assert body["approval"]["decided_by"] == "ceo"


@pytest.mark.django_db
def test_approval_decision_endpoint_is_idempotent_for_same_payload(client):
    approval = create_pending_approval()
    payload = {
        "decision": ApprovalRequest.Status.REJECTED,
        "subject_version": 1,
        "action_payload": {"status": "COMPLETED"},
    }
    headers = {"Idempotency-Key": "approval-decision-2", "X-Correlation-ID": "corr-api-decision-2"}

    first = client.post(
        f"/api/v1/approvals/{approval.id}/decision/",
        data=json.dumps(payload),
        content_type="application/json",
        headers=headers,
    )
    second = client.post(
        f"/api/v1/approvals/{approval.id}/decision/",
        data=json.dumps(payload),
        content_type="application/json",
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()


@pytest.mark.django_db
def test_approval_decision_endpoint_rejects_tampered_payload(client):
    approval = create_pending_approval()

    response = client.post(
        f"/api/v1/approvals/{approval.id}/decision/",
        data=json.dumps(
            {
                "decision": ApprovalRequest.Status.APPROVED,
                "subject_version": 1,
                "action_payload": {"status": "FAILED"},
            }
        ),
        content_type="application/json",
        headers={"Idempotency-Key": "approval-decision-3", "X-Correlation-ID": "corr-api-decision-3"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "APPROVAL_PAYLOAD_MISMATCH"
