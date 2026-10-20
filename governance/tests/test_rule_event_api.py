import json

import pytest

from governance.models import AuditEvent, Rule, RuleEvaluation


pytestmark = pytest.mark.django_db


def headers(key: str) -> dict:
    return {"Idempotency-Key": key, "X-Correlation-ID": f"corr-{key}", "X-Actor-ID": "chief_of_staff"}


def create_active_rule(decision=RuleEvaluation.Decision.REQUIRE_APPROVAL):
    return Rule.objects.create(
        rule_id="invoice-event",
        version=1,
        name="Invoice event rule",
        owner="chief_of_staff",
        status=Rule.Status.ACTIVE,
        conditions={"field": "event_type", "operator": "equals", "value": "invoice.received"},
        decision=decision,
        reason_codes=["INVOICE_REVIEW_REQUIRED"],
    )


def test_rule_event_endpoint_evaluates_active_rule_and_audits(client):
    rule = create_active_rule()
    payload = {
        "source": "mailbox",
        "external_event_id": "msg-1",
        "event": {"event_type": "invoice.received", "amount": 120},
    }

    response = client.post("/api/v1/rules/events/", data=json.dumps(payload), content_type="application/json", headers=headers("rule-event-1"))

    assert response.status_code == 201
    body = response.json()["evaluation"]
    assert body["decision"] == RuleEvaluation.Decision.REQUIRE_APPROVAL
    assert body["rule_id"] == str(rule.id)
    assert AuditEvent.objects.filter(action="governance.rule_event.evaluated").exists()


def test_rule_event_endpoint_defaults_no_match_to_needs_more_data(client):
    create_active_rule(decision=RuleEvaluation.Decision.ALLOW)
    payload = {
        "source": "mailbox",
        "external_event_id": "msg-2",
        "event": {"event_type": "newsletter.received"},
    }

    response = client.post("/api/v1/rules/events/", data=json.dumps(payload), content_type="application/json", headers=headers("rule-event-2"))

    assert response.status_code == 201
    body = response.json()["evaluation"]
    assert body["decision"] == RuleEvaluation.Decision.NEEDS_MORE_DATA
    assert body["reason_codes"] == ["NO_MATCHING_ACTIVE_RULE"]


def test_rule_event_endpoint_is_idempotent(client):
    create_active_rule()
    payload = {
        "source": "mailbox",
        "external_event_id": "msg-3",
        "event": {"event_type": "invoice.received"},
    }

    first = client.post("/api/v1/rules/events/", data=json.dumps(payload), content_type="application/json", headers=headers("rule-event-3"))
    second = client.post("/api/v1/rules/events/", data=json.dumps(payload), content_type="application/json", headers=headers("rule-event-3"))

    assert first.status_code == 201
    assert second.status_code == 201
    assert RuleEvaluation.objects.count() == 1
    assert AuditEvent.objects.filter(action="governance.rule_event.evaluated").count() == 1
