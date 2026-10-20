import pytest

from core.models import MemoryRecord
from governance.models import AuditEvent


@pytest.fixture
def memory_records():
    return [
        MemoryRecord.objects.create(
            record_type=MemoryRecord.RecordType.LESSON,
            title="Keep Sharons separate from product repositories",
            content={"summary": "Product code stays outside Sharons."},
            source_type=MemoryRecord.SourceType.HUMAN_ENTRY,
            source_id="manual-1",
            owner="chief_of_staff",
            classification=MemoryRecord.Classification.INTERNAL,
        ),
        MemoryRecord.objects.create(
            record_type=MemoryRecord.RecordType.FACT,
            title="Finance source of truth uses PostgreSQL",
            content={"database": "PostgreSQL"},
            source_type=MemoryRecord.SourceType.DOCUMENT,
            source_id="finance-spec",
            owner="finance_agent",
            classification=MemoryRecord.Classification.CONFIDENTIAL,
            verification_status=MemoryRecord.VerificationStatus.VERIFIED,
        ),
    ]


@pytest.mark.django_db
def test_history_search_returns_memory_records(client, memory_records):
    response = client.get("/api/v1/history/search/")

    assert response.status_code == 200
    body = response.json()
    assert len(body["memory"]) == 2
    assert {item["title"] for item in body["memory"]} == {
        "Keep Sharons separate from product repositories",
        "Finance source of truth uses PostgreSQL",
    }


@pytest.mark.django_db
def test_history_search_filters_by_text(client, memory_records):
    response = client.get("/api/v1/history/search/", {"q": "finance"})

    assert response.status_code == 200
    body = response.json()
    assert [item["title"] for item in body["memory"]] == ["Finance source of truth uses PostgreSQL"]


@pytest.mark.django_db
def test_history_search_filters_by_structured_fields(client, memory_records):
    response = client.get(
        "/api/v1/history/search/",
        {
            "record_type": MemoryRecord.RecordType.FACT,
            "classification": MemoryRecord.Classification.CONFIDENTIAL,
            "verification_status": MemoryRecord.VerificationStatus.VERIFIED,
            "source_type": MemoryRecord.SourceType.DOCUMENT,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["source_id"] for item in body["memory"]] == ["finance-spec"]


@pytest.mark.django_db
def test_history_search_respects_limit(client, memory_records):
    response = client.get("/api/v1/history/search/", {"limit": "1"})

    assert response.status_code == 200
    assert len(response.json()["memory"]) == 1


@pytest.mark.django_db
def test_history_search_rejects_invalid_filter(client):
    response = client.get("/api/v1/history/search/", {"classification": "SECRETISH"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_HISTORY_FILTER"


@pytest.mark.django_db
def test_history_search_is_read_only(client, memory_records):
    response = client.get("/api/v1/history/search/", {"q": "Sharons"})

    assert response.status_code == 200
    assert MemoryRecord.objects.count() == 2
    assert AuditEvent.objects.count() == 0
