import json

import pytest

from core.models import MemoryRecord
from governance.models import AuditEvent


@pytest.mark.django_db
def test_memory_create_endpoint_creates_record_and_audit_event(client):
    response = client.post(
        "/api/v1/memory/",
        data=json.dumps(
            {
                "record_type": MemoryRecord.RecordType.LESSON,
                "title": "Keep Sharons separate from product repositories",
                "content": {"summary": "Product code stays in product repos."},
                "source_type": MemoryRecord.SourceType.HUMAN_ENTRY,
                "source_id": "manual-1",
                "owner": "chief_of_staff",
                "classification": MemoryRecord.Classification.INTERNAL,
            }
        ),
        content_type="application/json",
        headers={"Idempotency-Key": "memory-1", "X-Correlation-ID": "corr-memory-1"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["memory"]["record_type"] == MemoryRecord.RecordType.LESSON
    assert body["memory"]["verification_status"] == MemoryRecord.VerificationStatus.UNVERIFIED
    assert MemoryRecord.objects.count() == 1
    assert AuditEvent.objects.filter(
        action="core.memory.created",
        correlation_id="corr-memory-1",
        metadata__record_type=MemoryRecord.RecordType.LESSON,
    ).exists()


@pytest.mark.django_db
def test_memory_create_endpoint_is_idempotent(client):
    payload = {
        "record_type": MemoryRecord.RecordType.FACT,
        "title": "Sharons uses PostgreSQL",
        "content": {"database": "PostgreSQL"},
        "source_type": MemoryRecord.SourceType.DOCUMENT,
        "source_id": "docs/chief_of_staff/SPEC_HE.md",
        "owner": "chief_of_staff",
    }
    headers = {"Idempotency-Key": "memory-2", "X-Correlation-ID": "corr-memory-2"}

    first = client.post("/api/v1/memory/", data=json.dumps(payload), content_type="application/json", headers=headers)
    second = client.post("/api/v1/memory/", data=json.dumps(payload), content_type="application/json", headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()
    assert MemoryRecord.objects.count() == 1
    assert AuditEvent.objects.count() == 1


@pytest.mark.django_db
def test_memory_create_endpoint_rejects_reused_idempotency_key_with_different_payload(client):
    headers = {"Idempotency-Key": "memory-3", "X-Correlation-ID": "corr-memory-3"}
    client.post(
        "/api/v1/memory/",
        data=json.dumps(
            {
                "record_type": MemoryRecord.RecordType.FACT,
                "title": "First fact",
                "content": {"value": 1},
                "source_type": MemoryRecord.SourceType.HUMAN_ENTRY,
                "source_id": "manual-3",
                "owner": "chief_of_staff",
            }
        ),
        content_type="application/json",
        headers=headers,
    )

    response = client.post(
        "/api/v1/memory/",
        data=json.dumps(
            {
                "record_type": MemoryRecord.RecordType.FACT,
                "title": "Different fact",
                "content": {"value": 2},
                "source_type": MemoryRecord.SourceType.HUMAN_ENTRY,
                "source_id": "manual-3",
                "owner": "chief_of_staff",
            }
        ),
        content_type="application/json",
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


@pytest.mark.django_db
def test_memory_create_endpoint_links_superseded_record(client):
    old_record = MemoryRecord.objects.create(
        record_type=MemoryRecord.RecordType.SOP,
        title="Old weekly review SOP",
        content={"cadence": "ad hoc"},
        source_type=MemoryRecord.SourceType.HUMAN_ENTRY,
        source_id="manual-old",
        owner="chief_of_staff",
    )

    response = client.post(
        "/api/v1/memory/",
        data=json.dumps(
            {
                "record_type": MemoryRecord.RecordType.SOP,
                "title": "Weekly review SOP",
                "content": {"cadence": "weekly"},
                "source_type": MemoryRecord.SourceType.HUMAN_ENTRY,
                "source_id": "manual-new",
                "owner": "chief_of_staff",
                "supersedes_id": str(old_record.id),
            }
        ),
        content_type="application/json",
        headers={"Idempotency-Key": "memory-4", "X-Correlation-ID": "corr-memory-4"},
    )

    assert response.status_code == 201
    assert response.json()["memory"]["supersedes_id"] == str(old_record.id)


@pytest.mark.django_db
def test_memory_create_endpoint_rejects_verified_conversation_decision(client):
    response = client.post(
        "/api/v1/memory/",
        data=json.dumps(
            {
                "record_type": MemoryRecord.RecordType.DECISION,
                "title": "Decision from chat",
                "content": {"decision": "Ship it"},
                "source_type": MemoryRecord.SourceType.CONVERSATION,
                "source_id": "conversation-1",
                "owner": "chief_of_staff",
                "verification_status": MemoryRecord.VerificationStatus.VERIFIED,
            }
        ),
        content_type="application/json",
        headers={"Idempotency-Key": "memory-5", "X-Correlation-ID": "corr-memory-5"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_MEMORY_PAYLOAD"
    assert MemoryRecord.objects.count() == 0


@pytest.mark.django_db
def test_memory_create_endpoint_rejects_embedding_reference_in_initial_slice(client):
    response = client.post(
        "/api/v1/memory/",
        data=json.dumps(
            {
                "record_type": MemoryRecord.RecordType.REFERENCE,
                "title": "Embedding ref not yet supported",
                "content": {"summary": "No embeddings yet"},
                "source_type": MemoryRecord.SourceType.DOCUMENT,
                "source_id": "doc-1",
                "owner": "chief_of_staff",
                "embedding_reference": "vector://abc",
            }
        ),
        content_type="application/json",
        headers={"Idempotency-Key": "memory-6", "X-Correlation-ID": "corr-memory-6"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_MEMORY_PAYLOAD"
