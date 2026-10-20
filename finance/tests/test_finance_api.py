import json

import pytest

from finance.models import FinancialRecord
from governance.models import AuditEvent, RuleEngineRun, RuleEngineWorkItem


@pytest.fixture
def dashboard_user(django_user_model):
    return django_user_model.objects.create_user(username="finance", password="secret")


def income_payload(**overrides):
    payload = {
        "record_type": FinancialRecord.RecordType.INCOME,
        "occurred_on": "2026-09-17",
        "amount": "120.50",
        "currency": "ILS",
        "source": "manual",
        "category": "subscription",
        "description": "Mental Trainer beta payment",
        "external_reference": "income-1",
        "metadata": {"project": "mental_trainer"},
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
def test_financial_record_create_requires_headers(client):
    response = client.post(
        "/api/v1/finance/records/create/",
        data=json.dumps(income_payload()),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_FINANCE_PAYLOAD"


@pytest.mark.django_db
def test_financial_record_create_records_audit(client):
    response = client.post(
        "/api/v1/finance/records/create/",
        data=json.dumps(income_payload()),
        content_type="application/json",
        headers={"Idempotency-Key": "finance-create-1", "X-Correlation-ID": "corr-finance-1", "X-Actor-ID": "finance_agent"},
    )

    assert response.status_code == 201
    record = FinancialRecord.objects.get()
    assert record.amount == "120.50" or str(record.amount) == "120.50"
    assert record.reconciliation_status == FinancialRecord.ReconciliationStatus.UNRECONCILED
    assert record.metadata["rules_engine_run_id"]
    assert record.metadata["rules_engine_decision"] in {"allow_read_only", "recommendation_only"}
    assert RuleEngineRun.objects.filter(event_type="finance_document.classify").count() == 1
    assert AuditEvent.objects.filter(action="finance.record.created", object_id=str(record.id)).exists()


@pytest.mark.django_db
def test_financial_record_create_rejects_duplicate_external_reference(client):
    headers = {"Idempotency-Key": "finance-create-2", "X-Correlation-ID": "corr-finance-2"}
    client.post("/api/v1/finance/records/create/", data=json.dumps(income_payload()), content_type="application/json", headers=headers)

    response = client.post(
        "/api/v1/finance/records/create/",
        data=json.dumps(income_payload(description="Duplicate payment")),
        content_type="application/json",
        headers={"Idempotency-Key": "finance-create-3", "X-Correlation-ID": "corr-finance-3"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "FINANCE_RECORD_CONFLICT"


@pytest.mark.django_db
def test_financial_records_list_filters(client):
    FinancialRecord.objects.create(**income_payload(), created_by="finance_agent")
    FinancialRecord.objects.create(
        **income_payload(
            record_type=FinancialRecord.RecordType.API_COST,
            amount="10.00",
            description="OpenAI API usage",
            external_reference="api-1",
        ),
        created_by="finance_agent",
    )

    response = client.get("/api/v1/finance/records/", {"record_type": FinancialRecord.RecordType.API_COST})

    assert response.status_code == 200
    records = response.json()["financial_records"]
    assert len(records) == 1
    assert records[0]["description"] == "OpenAI API usage"


@pytest.mark.django_db
def test_financial_record_reconcile_updates_status_and_audits(client):
    record = FinancialRecord.objects.create(**income_payload(), created_by="finance_agent")

    response = client.post(
        f"/api/v1/finance/records/{record.id}/reconcile/",
        data=json.dumps({"reconciliation_status": FinancialRecord.ReconciliationStatus.RECONCILED, "notes": "Matched bank line."}),
        content_type="application/json",
        headers={"Idempotency-Key": "finance-reconcile-1", "X-Correlation-ID": "corr-finance-4", "X-Actor-ID": "finance_agent"},
    )

    assert response.status_code == 200
    record.refresh_from_db()
    assert record.reconciliation_status == FinancialRecord.ReconciliationStatus.RECONCILED
    assert record.reconciliation_notes == "Matched bank line."
    assert AuditEvent.objects.filter(action="finance.record.reconciled", object_id=str(record.id)).exists()


@pytest.mark.django_db
def test_finance_dashboard_requires_login(client):
    response = client.get("/finance/")

    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


@pytest.mark.django_db
def test_finance_dashboard_renders_summary(client, dashboard_user):
    FinancialRecord.objects.create(**income_payload(), created_by="finance_agent")
    FinancialRecord.objects.create(
        **income_payload(
            record_type=FinancialRecord.RecordType.SERVER_COST,
            amount="20.00",
            description="Server cost",
            external_reference="server-1",
        ),
        created_by="finance_agent",
    )
    run = RuleEngineRun.objects.create(
        source="manual",
        external_event_id="finance-work-1",
        event_type="finance_document.classify",
        event_payload={},
        dry_run=True,
        final_decision="require_approval",
        risk_level="medium",
        reason_codes=["PAYABLE_INVOICE_REQUIRES_APPROVAL"],
        raw_result={},
    )
    RuleEngineWorkItem.objects.create(
        run=run,
        item_type="APPROVAL_REQUIRED_ACTION",
        action_type="create_approval_request",
        title="Review payable invoice",
        component="sharons_finance",
        purpose="human_invoice_approval",
        status=RuleEngineWorkItem.Status.ASSIGNED,
        owner_agent_id="finance_agent",
    )

    client.force_login(dashboard_user)
    response = client.get("/finance/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "Finance" in content
    assert "Mental Trainer beta payment" in content
    assert "Server cost" in content
    assert "Rule Engine Work" in content
    assert "Review payable invoice" in content


@pytest.mark.django_db
def test_finance_dashboard_can_complete_rule_engine_work_item(client, dashboard_user):
    run = RuleEngineRun.objects.create(
        source="manual",
        external_event_id="finance-work-2",
        event_type="finance_document.classify",
        event_payload={},
        dry_run=True,
        final_decision="require_approval",
        risk_level="medium",
        reason_codes=["PAYABLE_INVOICE_REQUIRES_APPROVAL"],
        raw_result={},
    )
    item = RuleEngineWorkItem.objects.create(
        run=run,
        item_type="APPROVAL_REQUIRED_ACTION",
        action_type="create_approval_request",
        title="Review payable invoice",
        component="sharons_finance",
        purpose="human_invoice_approval",
        status=RuleEngineWorkItem.Status.ASSIGNED,
        owner_agent_id="finance_agent",
    )

    client.force_login(dashboard_user)
    response = client.post("/finance/", {"action": "complete_rule_engine_work_item", "item_id": str(item.id)})

    assert response.status_code == 302
    item.refresh_from_db()
    assert item.status == RuleEngineWorkItem.Status.COMPLETED
    assert AuditEvent.objects.filter(
        action="governance.rules_engine.work_item.updated",
        actor_id="finance",
        object_id=str(item.id),
    ).exists()
