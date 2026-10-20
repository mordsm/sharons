import json

import pytest

from governance.models import AuditEvent, RuleEngineRun, RuleEngineWorkItem
from governance.services import route_rule_engine_work_item_owner


pytestmark = pytest.mark.django_db


@pytest.fixture
def work_item():
    run = RuleEngineRun.objects.create(
        source="gmail_mock",
        external_event_id="msg-work-1",
        event_type="inbound_email.route",
        event_payload={},
        dry_run=True,
        final_decision="require_approval",
        risk_level="high",
        reason_codes=["SENSITIVE_EMAIL_REQUIRES_HUMAN_REVIEW"],
        raw_result={},
    )
    return RuleEngineWorkItem.objects.create(
        run=run,
        item_type="APPROVAL_REQUIRED_ACTION",
        action_type="create_file_link_proposal",
        title="File inbound email attachment",
        component="sharons_files",
        purpose="safe_internal_filing",
        payload={"no_external_action": True},
    )


def test_rules_engine_work_items_list_returns_queue_items(client, work_item):
    response = client.get("/api/v1/rules-engine/work-items/")

    assert response.status_code == 200
    body = response.json()
    assert len(body["work_items"]) == 1
    assert body["work_items"][0]["id"] == str(work_item.id)
    assert body["work_items"][0]["status"] == RuleEngineWorkItem.Status.OPEN


def test_rules_engine_work_items_list_filters_by_status(client, work_item):
    response = client.get("/api/v1/rules-engine/work-items/", {"status": RuleEngineWorkItem.Status.COMPLETED})

    assert response.status_code == 200
    assert response.json()["work_items"] == []


def test_rules_engine_work_item_update_assigns_owner_and_audits(client, work_item):
    response = client.post(
        f"/api/v1/rules-engine/work-items/{work_item.id}/update/",
        data=json.dumps({"owner_agent_id": "executive_assistant"}),
        content_type="application/json",
        headers={"Idempotency-Key": "work-item-update-1", "X-Correlation-ID": "corr-work-item-1", "X-Actor-ID": "chief_of_staff"},
    )

    assert response.status_code == 200
    work_item.refresh_from_db()
    assert work_item.owner_agent_id == "executive_assistant"
    assert work_item.status == RuleEngineWorkItem.Status.ASSIGNED
    assert AuditEvent.objects.filter(action="governance.rules_engine.work_item.updated", object_id=str(work_item.id)).exists()


def test_rules_engine_work_item_update_completes_assigned_item(client, work_item):
    work_item.owner_agent_id = "executive_assistant"
    work_item.status = RuleEngineWorkItem.Status.ASSIGNED
    work_item.save(update_fields=["owner_agent_id", "status"])

    response = client.post(
        f"/api/v1/rules-engine/work-items/{work_item.id}/update/",
        data=json.dumps({"status": RuleEngineWorkItem.Status.COMPLETED}),
        content_type="application/json",
        headers={"Idempotency-Key": "work-item-update-2", "X-Correlation-ID": "corr-work-item-2"},
    )

    assert response.status_code == 200
    work_item.refresh_from_db()
    assert work_item.status == RuleEngineWorkItem.Status.COMPLETED


def test_rules_engine_work_item_update_rejects_completion_without_owner(client, work_item):
    response = client.post(
        f"/api/v1/rules-engine/work-items/{work_item.id}/update/",
        data=json.dumps({"status": RuleEngineWorkItem.Status.COMPLETED}),
        content_type="application/json",
        headers={"Idempotency-Key": "work-item-update-3", "X-Correlation-ID": "corr-work-item-3"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_RULE_ENGINE_WORK_ITEM_UPDATE"


def test_rule_engine_work_item_routing_selects_finance_owner():
    run = RuleEngineRun.objects.create(
        source="finance_mock",
        external_event_id="invoice-routing-1",
        event_type="finance_document.classify",
        event_payload={},
        dry_run=True,
        final_decision="require_approval",
        risk_level="medium",
        reason_codes=["FINANCE_DOCUMENT_REVIEW"],
        raw_result={},
    )

    owner = route_rule_engine_work_item_owner(
        {
            "item_type": "APPROVAL_REQUIRED_ACTION",
            "action_type": "create_payment_review",
            "component": "sharons_finance",
            "purpose": "invoice_payment_review",
        },
        run,
    )

    assert owner == "finance_agent"


def test_rule_engine_work_item_routing_keeps_finance_route_review_with_finance():
    run = RuleEngineRun.objects.create(
        source="finance_mock",
        external_event_id="invoice-route-review-1",
        event_type="finance_document.classify",
        event_payload={},
        dry_run=True,
        final_decision="require_approval",
        risk_level="medium",
        reason_codes=["PAYABLE_INVOICE_REQUIRES_APPROVAL"],
        raw_result={},
    )

    owner = route_rule_engine_work_item_owner(
        {
            "item_type": "ROUTE_REVIEW",
            "component": "sharons_finance",
            "purpose": "record_invoice_review",
        },
        run,
    )

    assert owner == "finance_agent"


def test_rule_engine_work_item_routing_selects_executive_assistant_for_email_files():
    run = RuleEngineRun.objects.create(
        source="gmail_mock",
        external_event_id="email-routing-1",
        event_type="inbound_email.route",
        event_payload={},
        dry_run=True,
        final_decision="allow",
        risk_level="low",
        raw_result={},
    )

    owner = route_rule_engine_work_item_owner(
        {
            "item_type": "INTERNAL_PROPOSAL",
            "action_type": "create_file_link_proposal",
            "component": "sharons_files",
            "purpose": "safe_internal_filing",
        },
        run,
    )

    assert owner == "executive_assistant"


def test_rule_engine_work_item_routing_selects_chief_of_staff_for_owner_review():
    run = RuleEngineRun.objects.create(
        source="gmail_mock",
        external_event_id="owner-routing-1",
        event_type="inbound_email.route",
        event_payload={},
        dry_run=True,
        final_decision="require_approval",
        risk_level="high",
        raw_result={},
    )

    owner = route_rule_engine_work_item_owner(
        {
            "item_type": "ROUTE_REVIEW",
            "component": "owner_review",
            "purpose": "review_sensitive_email",
        },
        run,
    )

    assert owner == "chief_of_staff"
