import json

import pytest

from governance.models import ApprovalRequest, AuditEvent, InboxEvent, Rule, RuleEngineRun, RuleEvaluation
from mailbox.models import MockEmailMessage


@pytest.fixture
def dashboard_user(django_user_model):
    return django_user_model.objects.create_user(username="ops", password="secret")


def email_payload(**overrides):
    payload = {
        "source": "gmail_mock",
        "external_event_id": "msg-1",
        "sender": "vendor@example.com",
        "subject": "Invoice for September",
        "body": "Attached is invoice 123.",
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
def test_mock_email_ingest_classifies_invoice_and_evaluates_rules(client):
    Rule.objects.create(
        rule_id="invoice-email-review",
        version=1,
        name="Invoices require approval",
        owner="chief_of_staff",
        status=Rule.Status.ACTIVE,
        conditions={"field": "classification", "operator": "equals", "value": MockEmailMessage.Classification.INVOICE},
        decision=RuleEvaluation.Decision.REQUIRE_APPROVAL,
        reason_codes=["INVOICE_EMAIL_REQUIRES_APPROVAL"],
    )

    response = client.post(
        "/api/v1/mailbox/mock-gmail/inbound/",
        data=json.dumps(email_payload()),
        content_type="application/json",
        headers={"Idempotency-Key": "email-ingest-1", "X-Correlation-ID": "corr-email-1", "X-Actor-ID": "gmail_mock"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"]["classification"] == MockEmailMessage.Classification.INVOICE
    assert body["email"]["proposed_action"]["type"] == "MANUAL_REVIEW"
    assert body["email"]["rule_decision"] == RuleEvaluation.Decision.REQUIRE_APPROVAL
    assert body["email"]["rule_reason_codes"] == ["INVOICE_EMAIL_REQUIRES_APPROVAL"]
    assert body["email"]["proposed_action"]["rules_engine_decision"] == "require_approval"
    assert body["email"]["proposed_action"]["approval_id"]
    assert InboxEvent.objects.count() == 1
    assert RuleEngineRun.objects.filter(event_type="inbound_email.route").count() == 1
    assert ApprovalRequest.objects.filter(action="governance.rules_engine.review").count() == 1
    assert AuditEvent.objects.filter(action="mailbox.mock_email.ingested").exists()


@pytest.mark.django_db
def test_mock_email_ingest_defaults_to_needs_more_data_without_rule(client):
    response = client.post(
        "/api/v1/mailbox/mock-gmail/inbound/",
        data=json.dumps(email_payload(subject="FYI product note", body="Sharing context only.")),
        content_type="application/json",
        headers={"Idempotency-Key": "email-ingest-2", "X-Correlation-ID": "corr-email-2"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"]["classification"] == MockEmailMessage.Classification.INFORMATION
    assert body["email"]["rule_decision"] == RuleEvaluation.Decision.NEEDS_MORE_DATA
    assert body["email"]["proposed_action"]["type"] == "STORE_INFORMATION"
    assert body["email"]["proposed_action"]["rules_engine_run_id"]


@pytest.mark.django_db
def test_mock_email_ingest_deduplicates_external_event(client):
    payload = email_payload(external_event_id="msg-dedupe")
    headers = {"Idempotency-Key": "email-ingest-3", "X-Correlation-ID": "corr-email-3"}
    first = client.post("/api/v1/mailbox/mock-gmail/inbound/", data=json.dumps(payload), content_type="application/json", headers=headers)
    second = client.post(
        "/api/v1/mailbox/mock-gmail/inbound/",
        data=json.dumps(payload),
        content_type="application/json",
        headers={"Idempotency-Key": "email-ingest-4", "X-Correlation-ID": "corr-email-4"},
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert MockEmailMessage.objects.count() == 1
    assert InboxEvent.objects.count() == 1


@pytest.mark.django_db
def test_mock_email_ingest_marks_personal_sensitive_for_restricted_review(client):
    response = client.post(
        "/api/v1/mailbox/mock-gmail/inbound/",
        data=json.dumps(email_payload(external_event_id="msg-sensitive", subject="Medical document", body="Diagnosis details attached.")),
        content_type="application/json",
        headers={"Idempotency-Key": "email-ingest-5", "X-Correlation-ID": "corr-email-5"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"]["classification"] == MockEmailMessage.Classification.PERSONAL_SENSITIVE
    assert body["email"]["proposed_action"]["type"] == "RESTRICT_AND_REVIEW"


@pytest.mark.django_db
def test_email_list_filters_by_classification(client):
    MockEmailMessage.objects.create(
        source="gmail_mock",
        external_event_id="msg-list-1",
        sender="vendor@example.com",
        subject="Invoice",
        body="Invoice",
        classification=MockEmailMessage.Classification.INVOICE,
        proposed_action={"type": "MANUAL_REVIEW"},
        rule_decision=RuleEvaluation.Decision.NEEDS_MORE_DATA,
    )

    response = client.get("/api/v1/mailbox/emails/", {"classification": MockEmailMessage.Classification.INVOICE})

    assert response.status_code == 200
    assert len(response.json()["emails"]) == 1


@pytest.mark.django_db
def test_inbox_dashboard_requires_login(client):
    response = client.get("/inbox/")

    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


@pytest.mark.django_db
def test_inbox_dashboard_renders_messages(client, dashboard_user):
    MockEmailMessage.objects.create(
        source="gmail_mock",
        external_event_id="msg-dashboard",
        sender="vendor@example.com",
        subject="Invoice",
        body="Invoice",
        classification=MockEmailMessage.Classification.INVOICE,
        proposed_action={"type": "MANUAL_REVIEW"},
        rule_decision=RuleEvaluation.Decision.NEEDS_MORE_DATA,
    )

    client.force_login(dashboard_user)
    response = client.get("/inbox/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "Mock Inbox" in content
    assert "Invoice" in content
    assert "MANUAL_REVIEW" in content
