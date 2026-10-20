import pytest
from django.utils import timezone

from governance.models import ApprovalRequest, AuditEvent
from governance.services import (
    ApprovalAlreadyDecidedError,
    ApprovalExpiredError,
    ApprovalPayloadMismatchError,
    ApprovalVersionMismatchError,
    create_approval_request,
    decide_approval_request,
)


def future_expiry():
    return timezone.now() + timezone.timedelta(hours=1)


@pytest.mark.django_db
def test_create_approval_request_binds_subject_payload_and_audit_event():
    approval = create_approval_request(
        subject_type="operations.Task",
        subject_id="task-1",
        subject_version=3,
        action="operations.task.complete",
        action_payload={"status": "COMPLETED"},
        requested_by="chief_of_staff",
        correlation_id="corr-approval-1",
        expires_at=future_expiry(),
        reason_codes=["HIGH_RISK_ACTION"],
    )

    assert approval.status == ApprovalRequest.Status.PENDING
    assert approval.subject_version == 3
    assert approval.action_payload_hash
    assert approval.reason_codes == ["HIGH_RISK_ACTION"]
    assert AuditEvent.objects.filter(
        action="governance.approval.requested",
        object_id=str(approval.id),
        correlation_id="corr-approval-1",
    ).exists()


@pytest.mark.django_db
def test_decide_approval_request_approves_exact_bound_action():
    approval = create_approval_request(
        subject_type="operations.Task",
        subject_id="task-2",
        subject_version=1,
        action="operations.task.complete",
        action_payload={"status": "COMPLETED"},
        requested_by="chief_of_staff",
        correlation_id="corr-approval-2",
        expires_at=future_expiry(),
    )

    decided = decide_approval_request(
        str(approval.id),
        decision=ApprovalRequest.Status.APPROVED,
        actor_id="ceo",
        subject_version=1,
        action_payload={"status": "COMPLETED"},
        correlation_id="corr-approval-2-decision",
    )

    assert decided.status == ApprovalRequest.Status.APPROVED
    assert decided.decided_by == "ceo"
    assert AuditEvent.objects.filter(
        action="governance.approval.decided",
        object_id=str(approval.id),
        metadata__decision=ApprovalRequest.Status.APPROVED,
    ).exists()


@pytest.mark.django_db
def test_decide_approval_request_rejects_subject_version_mismatch():
    approval = create_approval_request(
        subject_type="operations.Task",
        subject_id="task-3",
        subject_version=1,
        action="operations.task.complete",
        action_payload={"status": "COMPLETED"},
        requested_by="chief_of_staff",
        correlation_id="corr-approval-3",
        expires_at=future_expiry(),
    )

    with pytest.raises(ApprovalVersionMismatchError):
        decide_approval_request(
            str(approval.id),
            decision=ApprovalRequest.Status.APPROVED,
            actor_id="ceo",
            subject_version=2,
            action_payload={"status": "COMPLETED"},
            correlation_id="corr-approval-3-decision",
        )

    approval.refresh_from_db()
    assert approval.status == ApprovalRequest.Status.PENDING


@pytest.mark.django_db
def test_decide_approval_request_rejects_payload_mismatch():
    approval = create_approval_request(
        subject_type="operations.Task",
        subject_id="task-4",
        subject_version=1,
        action="operations.task.complete",
        action_payload={"status": "COMPLETED"},
        requested_by="chief_of_staff",
        correlation_id="corr-approval-4",
        expires_at=future_expiry(),
    )

    with pytest.raises(ApprovalPayloadMismatchError):
        decide_approval_request(
            str(approval.id),
            decision=ApprovalRequest.Status.APPROVED,
            actor_id="ceo",
            subject_version=1,
            action_payload={"status": "FAILED"},
            correlation_id="corr-approval-4-decision",
        )

    approval.refresh_from_db()
    assert approval.status == ApprovalRequest.Status.PENDING


@pytest.mark.django_db
def test_expired_approval_cannot_be_approved():
    approval = create_approval_request(
        subject_type="operations.Task",
        subject_id="task-5",
        subject_version=1,
        action="operations.task.complete",
        action_payload={"status": "COMPLETED"},
        requested_by="chief_of_staff",
        correlation_id="corr-approval-5",
        expires_at=timezone.now() - timezone.timedelta(minutes=1),
    )

    with pytest.raises(ApprovalExpiredError):
        decide_approval_request(
            str(approval.id),
            decision=ApprovalRequest.Status.APPROVED,
            actor_id="ceo",
            subject_version=1,
            action_payload={"status": "COMPLETED"},
            correlation_id="corr-approval-5-decision",
        )

    approval.refresh_from_db()
    assert approval.status == ApprovalRequest.Status.EXPIRED


@pytest.mark.django_db
def test_decided_approval_cannot_be_decided_again():
    approval = create_approval_request(
        subject_type="operations.Task",
        subject_id="task-6",
        subject_version=1,
        action="operations.task.complete",
        action_payload={"status": "COMPLETED"},
        requested_by="chief_of_staff",
        correlation_id="corr-approval-6",
        expires_at=future_expiry(),
    )
    decide_approval_request(
        str(approval.id),
        decision=ApprovalRequest.Status.REJECTED,
        actor_id="ceo",
        subject_version=1,
        action_payload={"status": "COMPLETED"},
        correlation_id="corr-approval-6-decision",
    )

    with pytest.raises(ApprovalAlreadyDecidedError):
        decide_approval_request(
            str(approval.id),
            decision=ApprovalRequest.Status.APPROVED,
            actor_id="ceo",
            subject_version=1,
            action_payload={"status": "COMPLETED"},
            correlation_id="corr-approval-6-second-decision",
        )
