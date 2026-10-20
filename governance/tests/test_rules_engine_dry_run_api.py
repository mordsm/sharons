import json

import pytest
from django.utils import timezone

from governance.models import ApprovalRequest, AuditEvent, RuleEngineRun


pytestmark = pytest.mark.django_db


def headers(key: str) -> dict:
    return {"Idempotency-Key": key, "X-Correlation-ID": f"corr-{key}", "X-Actor-ID": "chief_of_staff"}


def finance_event(**payload_overrides):
    payload = {
        "source_system": "mail_manager",
        "received_at": timezone.now().isoformat(),
        "document_ref": "doc-fin-1",
        "document_kind_hint": "invoice",
        "vendor_name": "Acme Supplies",
        "amount": 1200,
        "currency": "USD",
        "due_date": "2026-10-15",
        "confidence_hint": 0.94,
    }
    payload.update(payload_overrides)
    return {
        "source": "sharons_test",
        "external_event_id": "fin-1",
        "event": {
            "event_id": "evt-fin-1",
            "event_type": "finance_document.classify",
            "event_version": "1.0",
            "source": "sharons",
            "user_id": "sharon",
            "occurred_at": timezone.now().isoformat(),
            "payload": payload,
        },
    }


def test_rules_engine_dry_run_invoice_creates_review_approval(client):
    response = client.post(
        "/api/v1/rules-engine/dry-run/",
        data=json.dumps(finance_event()),
        content_type="application/json",
        headers=headers("rules-engine-finance-1"),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["run"]["final_decision"] == "require_approval"
    assert body["run"]["dry_run"] is True
    assert body["approval"]["action"] == "governance.rules_engine.review"
    assert body["approval"]["status"] == ApprovalRequest.Status.PENDING
    assert RuleEngineRun.objects.count() == 1
    assert ApprovalRequest.objects.count() == 1
    assert AuditEvent.objects.filter(action="governance.rules_engine.dry_run_evaluated").exists()


def test_rules_engine_dry_run_safe_receipt_creates_internal_proposal_audit_only(client):
    payload = finance_event(
        document_ref="doc-receipt-1",
        document_kind_hint="receipt",
        paid_at="2026-09-27",
        payment_method="card",
        due_date=None,
    )
    payload["external_event_id"] = "fin-2"
    payload["event"]["event_id"] = "evt-fin-2"

    response = client.post(
        "/api/v1/rules-engine/dry-run/",
        data=json.dumps(payload),
        content_type="application/json",
        headers=headers("rules-engine-finance-2"),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["run"]["final_decision"] == "allow_read_only"
    assert body["approval"] is None
    assert body["run"]["allowed_actions"][0]["action_type"] == "create_file_link_proposal"
    assert ApprovalRequest.objects.count() == 0
    assert AuditEvent.objects.filter(action="governance.rules_engine.proposals_created").exists()


def test_rules_engine_dry_run_is_idempotent(client):
    payload = finance_event()

    first = client.post(
        "/api/v1/rules-engine/dry-run/",
        data=json.dumps(payload),
        content_type="application/json",
        headers=headers("rules-engine-idem-1"),
    )
    second = client.post(
        "/api/v1/rules-engine/dry-run/",
        data=json.dumps(payload),
        content_type="application/json",
        headers=headers("rules-engine-idem-1"),
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()
    assert RuleEngineRun.objects.count() == 1
    assert ApprovalRequest.objects.count() == 1
