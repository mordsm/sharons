import json

import pytest

from governance.models import AuditEvent, Rule, RuleEvaluation, RuleTestCase


def valid_rule_payload():
    return {
        "rule_id": "invoice-approval",
        "version": 1,
        "name": "Invoices require approval",
        "owner": "chief_of_staff",
        "trigger": {"event_type": "document_received"},
        "conditions": {"field": "document_type", "operator": "equals", "value": "invoice"},
        "decision": RuleEvaluation.Decision.REQUIRE_APPROVAL,
        "reason_codes": ["INVOICE_REQUIRES_APPROVAL"],
    }


@pytest.mark.django_db
def test_rule_proposal_creates_draft_rule_and_audit(client):
    response = client.post(
        "/api/v1/rules/proposals/",
        data=json.dumps(valid_rule_payload()),
        content_type="application/json",
        headers={"Idempotency-Key": "rule-proposal-1", "X-Correlation-ID": "corr-rule-1"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["rule"]["status"] == Rule.Status.DRAFT
    assert Rule.objects.count() == 1
    assert AuditEvent.objects.filter(action="governance.rule.proposed").exists()


@pytest.mark.django_db
def test_rule_proposal_rejects_invalid_operator(client):
    payload = valid_rule_payload()
    payload["conditions"] = {"field": "amount", "operator": "eval", "value": "amount < 100"}

    response = client.post(
        "/api/v1/rules/proposals/",
        data=json.dumps(payload),
        content_type="application/json",
        headers={"Idempotency-Key": "rule-proposal-2", "X-Correlation-ID": "corr-rule-2"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] in {"INVALID_RULE_PAYLOAD", "INVALID_RULE_CONDITION"}
    assert Rule.objects.count() == 0


@pytest.mark.django_db
def test_rule_validate_moves_draft_to_validated(client):
    rule = Rule.objects.create(**valid_rule_payload(), status=Rule.Status.DRAFT)

    response = client.post(
        f"/api/v1/rules/{rule.id}/validate/",
        content_type="application/json",
        headers={"Idempotency-Key": "rule-validate-1", "X-Correlation-ID": "corr-rule-3"},
    )

    assert response.status_code == 200
    rule.refresh_from_db()
    assert rule.status == Rule.Status.VALIDATED
    assert AuditEvent.objects.filter(action="governance.rule.validated", object_id=str(rule.id)).exists()


@pytest.mark.django_db
def test_rule_test_moves_validated_rule_to_tested(client):
    rule = Rule.objects.create(**valid_rule_payload(), status=Rule.Status.VALIDATED)
    payload = {
        "test_cases": [
            {
                "name": "invoice matches",
                "input_event": {"document_type": "invoice"},
                "expected_decision": RuleEvaluation.Decision.REQUIRE_APPROVAL,
                "expected_match": True,
            },
            {
                "name": "receipt does not match",
                "input_event": {"document_type": "receipt"},
                "expected_decision": RuleEvaluation.Decision.NEEDS_MORE_DATA,
                "expected_match": False,
            },
        ]
    }

    response = client.post(
        f"/api/v1/rules/{rule.id}/test/",
        data=json.dumps(payload),
        content_type="application/json",
        headers={"Idempotency-Key": "rule-test-1", "X-Correlation-ID": "corr-rule-4"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["all_passed"] is True
    rule.refresh_from_db()
    assert rule.status == Rule.Status.TESTED
    assert RuleTestCase.objects.filter(rule=rule, passed=True).count() == 2


@pytest.mark.django_db
def test_rule_test_returns_conflict_and_persists_failed_cases(client):
    rule = Rule.objects.create(**valid_rule_payload(), status=Rule.Status.VALIDATED)
    payload = {
        "test_cases": [
            {
                "name": "wrong expectation",
                "input_event": {"document_type": "invoice"},
                "expected_decision": RuleEvaluation.Decision.ALLOW,
                "expected_match": True,
            }
        ]
    }

    response = client.post(
        f"/api/v1/rules/{rule.id}/test/",
        data=json.dumps(payload),
        content_type="application/json",
        headers={"Idempotency-Key": "rule-test-2", "X-Correlation-ID": "corr-rule-5"},
    )

    assert response.status_code == 409
    body = response.json()
    assert body["all_passed"] is False
    rule.refresh_from_db()
    assert rule.status == Rule.Status.VALIDATED
    assert RuleTestCase.objects.filter(rule=rule, passed=False).count() == 1
