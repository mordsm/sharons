import json

import pytest

from governance.models import ApprovalRequest, AuditEvent, Rule, RuleEvaluation
from governance.services import decide_approval_request


def make_tested_rule():
    return Rule.objects.create(
        rule_id="invoice-approval",
        version=1,
        name="Invoices require approval",
        owner="chief_of_staff",
        status=Rule.Status.TESTED,
        trigger={"event_type": "document_received"},
        conditions={"field": "document_type", "operator": "equals", "value": "invoice"},
        decision=RuleEvaluation.Decision.REQUIRE_APPROVAL,
        reason_codes=["INVOICE_REQUIRES_APPROVAL"],
    )


@pytest.mark.django_db
def test_rule_activation_request_creates_bound_approval(client):
    rule = make_tested_rule()

    response = client.post(
        f"/api/v1/rules/{rule.id}/activation-request/",
        data=json.dumps({"expires_hours": 24}),
        content_type="application/json",
        headers={"Idempotency-Key": "rule-activation-request-1", "X-Correlation-ID": "corr-activate-1"},
    )

    assert response.status_code == 201
    approval = ApprovalRequest.objects.get()
    assert approval.subject_type == "governance.Rule"
    assert approval.subject_id == str(rule.id)
    assert approval.subject_version == rule.version
    assert approval.action == "governance.rule.activate"
    assert approval.action_payload == {"rule_id": rule.rule_id, "version": rule.version, "status": Rule.Status.ACTIVE}


@pytest.mark.django_db
def test_rule_activation_requires_tested_rule(client):
    rule = make_tested_rule()
    rule.status = Rule.Status.VALIDATED
    rule.save(update_fields=["status"])

    response = client.post(
        f"/api/v1/rules/{rule.id}/activation-request/",
        data=json.dumps({"expires_hours": 24}),
        content_type="application/json",
        headers={"Idempotency-Key": "rule-activation-request-2", "X-Correlation-ID": "corr-activate-2"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RULE_LIFECYCLE_ERROR"


@pytest.mark.django_db
def test_rule_activate_requires_approved_bound_approval(client):
    rule = make_tested_rule()
    approval_response = client.post(
        f"/api/v1/rules/{rule.id}/activation-request/",
        data=json.dumps({"expires_hours": 24}),
        content_type="application/json",
        headers={"Idempotency-Key": "rule-activation-request-3", "X-Correlation-ID": "corr-activate-3"},
    )
    approval_id = approval_response.json()["approval"]["id"]

    response = client.post(
        f"/api/v1/rules/{rule.id}/activate/",
        data=json.dumps({"approval_id": approval_id}),
        content_type="application/json",
        headers={"Idempotency-Key": "rule-activate-1", "X-Correlation-ID": "corr-activate-4"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RULE_ACTIVATION_APPROVAL_REQUIRED"
    rule.refresh_from_db()
    assert rule.status == Rule.Status.TESTED


@pytest.mark.django_db
def test_rule_activate_with_approved_exact_approval(client):
    rule = make_tested_rule()
    approval_response = client.post(
        f"/api/v1/rules/{rule.id}/activation-request/",
        data=json.dumps({"expires_hours": 24}),
        content_type="application/json",
        headers={"Idempotency-Key": "rule-activation-request-4", "X-Correlation-ID": "corr-activate-5"},
    )
    approval = ApprovalRequest.objects.get(id=approval_response.json()["approval"]["id"])
    decide_approval_request(
        str(approval.id),
        decision=ApprovalRequest.Status.APPROVED,
        actor_id="ceo",
        subject_version=rule.version,
        action_payload={"rule_id": rule.rule_id, "version": rule.version, "status": Rule.Status.ACTIVE},
        correlation_id="corr-activate-approval",
    )

    response = client.post(
        f"/api/v1/rules/{rule.id}/activate/",
        data=json.dumps({"approval_id": str(approval.id)}),
        content_type="application/json",
        headers={"Idempotency-Key": "rule-activate-2", "X-Correlation-ID": "corr-activate-6", "X-Actor-ID": "chief_of_staff"},
    )

    assert response.status_code == 200
    rule.refresh_from_db()
    assert rule.status == Rule.Status.ACTIVE
    assert rule.approved_by == "ceo"
    assert AuditEvent.objects.filter(action="governance.rule.activated", object_id=str(rule.id)).exists()


@pytest.mark.django_db
def test_rule_activate_rejects_approval_bound_to_other_rule(client):
    rule = make_tested_rule()
    other_rule = Rule.objects.create(
        rule_id="receipt-approval",
        version=1,
        name="Receipts require review",
        owner="chief_of_staff",
        status=Rule.Status.TESTED,
        conditions={"field": "document_type", "operator": "equals", "value": "receipt"},
        decision=RuleEvaluation.Decision.REQUIRE_APPROVAL,
    )
    approval_response = client.post(
        f"/api/v1/rules/{other_rule.id}/activation-request/",
        data=json.dumps({"expires_hours": 24}),
        content_type="application/json",
        headers={"Idempotency-Key": "rule-activation-request-5", "X-Correlation-ID": "corr-activate-7"},
    )
    approval = ApprovalRequest.objects.get(id=approval_response.json()["approval"]["id"])
    decide_approval_request(
        str(approval.id),
        decision=ApprovalRequest.Status.APPROVED,
        actor_id="ceo",
        subject_version=other_rule.version,
        action_payload={"rule_id": other_rule.rule_id, "version": other_rule.version, "status": Rule.Status.ACTIVE},
        correlation_id="corr-activate-approval-other",
    )

    response = client.post(
        f"/api/v1/rules/{rule.id}/activate/",
        data=json.dumps({"approval_id": str(approval.id)}),
        content_type="application/json",
        headers={"Idempotency-Key": "rule-activate-3", "X-Correlation-ID": "corr-activate-8"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RULE_ACTIVATION_APPROVAL_REQUIRED"
    rule.refresh_from_db()
    assert rule.status == Rule.Status.TESTED
