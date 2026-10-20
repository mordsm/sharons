import pytest

from governance.models import AuditEvent


@pytest.fixture
def audit_events():
    return [
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id="chief_of_staff",
            action="operations.task.transitioned",
            object_type="operations.Task",
            object_id="task-1",
            correlation_id="corr-1",
            metadata={"to_status": "APPROVED"},
        ),
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.HUMAN,
            actor_id="ceo",
            action="governance.approval.decided",
            object_type="governance.ApprovalRequest",
            object_id="approval-1",
            correlation_id="corr-2",
            metadata={"decision": "APPROVED"},
        ),
    ]


@pytest.mark.django_db
def test_audit_list_returns_events(client, audit_events):
    response = client.get("/api/v1/audit/")

    assert response.status_code == 200
    body = response.json()
    assert len(body["audit_events"]) == 2
    assert {event["action"] for event in body["audit_events"]} == {
        "operations.task.transitioned",
        "governance.approval.decided",
    }


@pytest.mark.django_db
def test_audit_list_filters_by_structured_fields(client, audit_events):
    response = client.get(
        "/api/v1/audit/",
        {
            "actor_type": AuditEvent.ActorType.HUMAN,
            "actor_id": "ceo",
            "action": "governance.approval.decided",
            "object_type": "governance.ApprovalRequest",
            "object_id": "approval-1",
            "correlation_id": "corr-2",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert [event["object_id"] for event in body["audit_events"]] == ["approval-1"]


@pytest.mark.django_db
def test_audit_list_respects_limit(client, audit_events):
    response = client.get("/api/v1/audit/", {"limit": "1"})

    assert response.status_code == 200
    assert len(response.json()["audit_events"]) == 1


@pytest.mark.django_db
def test_audit_list_rejects_invalid_filter(client):
    response = client.get("/api/v1/audit/", {"actor_type": "ROBOT"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_AUDIT_FILTER"


@pytest.mark.django_db
def test_audit_list_is_read_only(client, audit_events):
    response = client.get("/api/v1/audit/", {"actor_id": "ceo"})

    assert response.status_code == 200
    assert AuditEvent.objects.count() == 2
