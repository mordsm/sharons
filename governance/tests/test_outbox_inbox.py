import pytest

from governance.models import AuditEvent, InboxEvent, OutboxMessage
from governance.services import (
    InvalidInboxPayloadError,
    InvalidOutboxPayloadError,
    OutboxIdempotencyConflictError,
    enqueue_outbox_message,
    record_inbox_event,
)


@pytest.mark.django_db
def test_enqueue_outbox_message_creates_pending_message_and_audit_event():
    message, created = enqueue_outbox_message(
        topic="approval.notification",
        payload={"approval_id": "approval-1"},
        idempotency_key="outbox-1",
        correlation_id="corr-outbox-1",
        actor_id="chief_of_staff",
    )

    assert created is True
    assert message.status == OutboxMessage.Status.PENDING
    assert message.attempts == 0
    assert message.payload == {"approval_id": "approval-1"}
    assert OutboxMessage.objects.count() == 1
    assert AuditEvent.objects.filter(
        action="governance.outbox.enqueued",
        correlation_id="corr-outbox-1",
        metadata__topic="approval.notification",
    ).exists()


@pytest.mark.django_db
def test_enqueue_outbox_message_is_idempotent_for_same_payload():
    first, first_created = enqueue_outbox_message(
        topic="approval.notification",
        payload={"approval_id": "approval-1"},
        idempotency_key="outbox-2",
        correlation_id="corr-outbox-2",
        actor_id="chief_of_staff",
    )
    second, second_created = enqueue_outbox_message(
        topic="approval.notification",
        payload={"approval_id": "approval-1"},
        idempotency_key="outbox-2",
        correlation_id="corr-outbox-2",
        actor_id="chief_of_staff",
    )

    assert first.id == second.id
    assert first_created is True
    assert second_created is False
    assert OutboxMessage.objects.count() == 1
    assert AuditEvent.objects.count() == 1


@pytest.mark.django_db
def test_enqueue_outbox_message_rejects_idempotency_conflict():
    enqueue_outbox_message(
        topic="approval.notification",
        payload={"approval_id": "approval-1"},
        idempotency_key="outbox-3",
        correlation_id="corr-outbox-3",
        actor_id="chief_of_staff",
    )

    with pytest.raises(OutboxIdempotencyConflictError):
        enqueue_outbox_message(
            topic="approval.notification",
            payload={"approval_id": "approval-2"},
            idempotency_key="outbox-3",
            correlation_id="corr-outbox-3",
            actor_id="chief_of_staff",
        )

    assert OutboxMessage.objects.count() == 1


@pytest.mark.django_db
def test_enqueue_outbox_message_rejects_invalid_payload():
    with pytest.raises(InvalidOutboxPayloadError):
        enqueue_outbox_message(
            topic="approval.notification",
            payload=[],
            idempotency_key="outbox-4",
            correlation_id="corr-outbox-4",
            actor_id="chief_of_staff",
        )


@pytest.mark.django_db
def test_record_inbox_event_creates_received_event_and_audit_event():
    event, created = record_inbox_event(
        source="gmail_mock",
        external_event_id="msg-1",
        payload={"subject": "Invoice"},
        correlation_id="corr-inbox-1",
        actor_id="gmail_adapter",
    )

    assert created is True
    assert event.status == InboxEvent.Status.RECEIVED
    assert event.payload == {"subject": "Invoice"}
    assert InboxEvent.objects.count() == 1
    assert AuditEvent.objects.filter(
        action="governance.inbox.received",
        correlation_id="corr-inbox-1",
        metadata__source="gmail_mock",
        metadata__external_event_id="msg-1",
    ).exists()


@pytest.mark.django_db
def test_record_inbox_event_deduplicates_by_source_and_external_event_id():
    first, first_created = record_inbox_event(
        source="gmail_mock",
        external_event_id="msg-2",
        payload={"subject": "Invoice"},
        correlation_id="corr-inbox-2",
        actor_id="gmail_adapter",
    )
    second, second_created = record_inbox_event(
        source="gmail_mock",
        external_event_id="msg-2",
        payload={"subject": "Changed copy"},
        correlation_id="corr-inbox-2b",
        actor_id="gmail_adapter",
    )

    assert first.id == second.id
    assert first_created is True
    assert second_created is False
    assert InboxEvent.objects.count() == 1
    assert InboxEvent.objects.get().payload == {"subject": "Invoice"}
    assert AuditEvent.objects.count() == 1


@pytest.mark.django_db
def test_record_inbox_event_rejects_invalid_payload():
    with pytest.raises(InvalidInboxPayloadError):
        record_inbox_event(
            source="gmail_mock",
            external_event_id="msg-3",
            payload=[],
            correlation_id="corr-inbox-3",
            actor_id="gmail_adapter",
        )
