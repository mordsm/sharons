import json

import pytest

from core.models import MemoryRecord
from governance.models import AuditEvent


pytestmark = pytest.mark.django_db


def headers(key: str) -> dict:
    return {"Idempotency-Key": key, "X-Correlation-ID": f"corr-{key}", "X-Actor-ID": "chief_of_staff"}


def test_event_create_records_audit_event_and_is_idempotent(client):
    payload = {
        "action": "cos.status.observed",
        "object_type": "operations.Task",
        "object_id": "task-1",
        "metadata": {"status": "BLOCKED"},
    }

    first = client.post("/api/v1/events/", data=json.dumps(payload), content_type="application/json", headers=headers("event-1"))
    second = client.post("/api/v1/events/", data=json.dumps(payload), content_type="application/json", headers=headers("event-1"))

    assert first.status_code == 201
    assert second.status_code == 201
    assert AuditEvent.objects.filter(action="cos.status.observed", object_id="task-1").count() == 1


def test_conversation_finalize_creates_unverified_memory(client):
    payload = {
        "conversation_id": "conv-1",
        "title": "Weekly direction notes",
        "summary": "CEO wants product and project management roles seeded before more finance work.",
        "decisions": ["Seed core company agents"],
        "action_items": ["Continue Chief of Staff completion"],
    }

    response = client.post(
        "/api/v1/conversation/finalize/",
        data=json.dumps(payload),
        content_type="application/json",
        headers=headers("conversation-1"),
    )

    assert response.status_code == 201
    record = MemoryRecord.objects.get(source_id="conv-1")
    assert record.record_type == MemoryRecord.RecordType.STATUS_SUMMARY
    assert record.source_type == MemoryRecord.SourceType.CONVERSATION
    assert record.verification_status == MemoryRecord.VerificationStatus.UNVERIFIED
    assert record.content["decisions"] == ["Seed core company agents"]


def test_conversation_finalize_does_not_create_verified_decision(client):
    payload = {
        "conversation_id": "conv-2",
        "title": "Decision-shaped summary",
        "summary": "This remains unverified memory.",
        "decisions": ["Looks like a decision"],
        "verification_status": MemoryRecord.VerificationStatus.VERIFIED,
    }

    response = client.post(
        "/api/v1/conversation/finalize/",
        data=json.dumps(payload),
        content_type="application/json",
        headers=headers("conversation-2"),
    )

    assert response.status_code == 201
    record = MemoryRecord.objects.get(source_id="conv-2")
    assert record.record_type == MemoryRecord.RecordType.STATUS_SUMMARY
    assert record.verification_status == MemoryRecord.VerificationStatus.UNVERIFIED
