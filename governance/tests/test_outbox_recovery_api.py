import json

import pytest

from governance.models import AuditEvent, OutboxMessage


@pytest.fixture
def dashboard_user(django_user_model):
    return django_user_model.objects.create_user(username="ops", password="secret")


@pytest.fixture
def failed_message():
    return OutboxMessage.objects.create(
        topic="approval.notification",
        payload={"approval_id": "approval-1"},
        status=OutboxMessage.Status.FAILED,
        attempts=2,
        idempotency_key="outbox-recovery-1",
        correlation_id="corr-outbox-recovery",
    )


@pytest.mark.django_db
def test_outbox_list_returns_messages(client, failed_message):
    response = client.get("/api/v1/outbox/", {"status": OutboxMessage.Status.FAILED})

    assert response.status_code == 200
    body = response.json()
    assert len(body["outbox_messages"]) == 1
    assert body["outbox_messages"][0]["id"] == str(failed_message.id)


@pytest.mark.django_db
def test_outbox_list_rejects_invalid_status(client):
    response = client.get("/api/v1/outbox/", {"status": "STUCKISH"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_OUTBOX_FILTER"


@pytest.mark.django_db
def test_outbox_retry_marks_failed_message_pending_and_audits(client, failed_message):
    response = client.post(
        f"/api/v1/outbox/{failed_message.id}/retry/",
        headers={"Idempotency-Key": "outbox-retry-1", "X-Correlation-ID": "corr-outbox-retry", "X-Actor-ID": "ops"},
    )

    assert response.status_code == 200
    failed_message.refresh_from_db()
    assert failed_message.status == OutboxMessage.Status.PENDING
    assert failed_message.next_attempt_at is not None
    assert AuditEvent.objects.filter(action="governance.outbox.retry_requested", object_id=str(failed_message.id)).exists()


@pytest.mark.django_db
def test_outbox_retry_rejects_pending_message(client):
    message = OutboxMessage.objects.create(
        topic="approval.notification",
        payload={"approval_id": "approval-1"},
        status=OutboxMessage.Status.PENDING,
        idempotency_key="outbox-recovery-2",
        correlation_id="corr-outbox-recovery-2",
    )

    response = client.post(
        f"/api/v1/outbox/{message.id}/retry/",
        headers={"Idempotency-Key": "outbox-retry-2", "X-Correlation-ID": "corr-outbox-retry-2"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "OUTBOX_RECOVERY_ERROR"


@pytest.mark.django_db
def test_outbox_dead_letter_marks_message_and_audits(client, failed_message):
    response = client.post(
        f"/api/v1/outbox/{failed_message.id}/dead-letter/",
        data=json.dumps({"reason": "Manual review says do not send."}),
        content_type="application/json",
        headers={"Idempotency-Key": "outbox-dead-letter-1", "X-Correlation-ID": "corr-outbox-dead", "X-Actor-ID": "ops"},
    )

    assert response.status_code == 200
    failed_message.refresh_from_db()
    assert failed_message.status == OutboxMessage.Status.DEAD_LETTER
    assert AuditEvent.objects.filter(action="governance.outbox.dead_lettered", object_id=str(failed_message.id)).exists()


@pytest.mark.django_db
def test_outbox_dashboard_requires_login(client):
    response = client.get("/outbox/")

    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


@pytest.mark.django_db
def test_outbox_dashboard_renders_messages(client, dashboard_user, failed_message):
    client.force_login(dashboard_user)
    response = client.get("/outbox/", {"status": OutboxMessage.Status.FAILED})

    assert response.status_code == 200
    content = response.content.decode()
    assert "Outbox Recovery" in content
    assert "approval.notification" in content
    assert "FAILED" in content
