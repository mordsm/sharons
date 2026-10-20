import pytest

from governance.models import Rule, RuleEvaluation
from governance.services import InvalidRuleConditionError, evaluate_condition, evaluate_rules


@pytest.mark.parametrize(
    ("condition", "event"),
    [
        ({"field": "document_type", "operator": "equals", "value": "invoice"}, {"document_type": "invoice"}),
        ({"field": "vendor_status", "operator": "not_equals", "value": "approved"}, {"vendor_status": "unknown"}),
        ({"field": "amount", "operator": "less_than", "value": 100}, {"amount": 50}),
        ({"field": "amount", "operator": "less_or_equal", "value": 100}, {"amount": 100}),
        ({"field": "amount", "operator": "greater_than", "value": 100}, {"amount": 150}),
        ({"field": "amount", "operator": "greater_or_equal", "value": 100}, {"amount": 100}),
        ({"field": "category", "operator": "in", "value": ["hosting", "api"]}, {"category": "api"}),
        ({"field": "category", "operator": "not_in", "value": ["salary"]}, {"category": "api"}),
        ({"field": "invoice_id", "operator": "exists"}, {"invoice_id": "INV-1"}),
        ({"field": "missing", "operator": "exists", "value": False}, {"invoice_id": "INV-1"}),
    ],
)
def test_leaf_operators_match(condition, event):
    matched, paths = evaluate_condition(condition, event)

    assert matched is True
    assert paths == ["$"]


def test_nested_boolean_structures_match():
    condition = {
        "all": [
            {"field": "document_type", "operator": "equals", "value": "invoice"},
            {
                "any": [
                    {"field": "amount", "operator": "less_than", "value": 100},
                    {"field": "vendor_status", "operator": "equals", "value": "approved"},
                ]
            },
            {"not": {"field": "risk", "operator": "equals", "value": "high"}},
        ]
    }

    matched, paths = evaluate_condition(
        condition,
        {"document_type": "invoice", "amount": 150, "vendor_status": "approved", "risk": "low"},
    )

    assert matched is True
    assert paths


def test_unsupported_operator_is_rejected():
    with pytest.raises(InvalidRuleConditionError):
        evaluate_condition({"field": "amount", "operator": "python_eval", "value": "amount < 100"}, {"amount": 50})


@pytest.mark.django_db
def test_active_matching_rule_returns_configured_decision():
    rule = Rule.objects.create(
        rule_id="invoice-approval",
        version=1,
        name="Invoice requires approval",
        owner="chief_of_staff",
        status=Rule.Status.ACTIVE,
        conditions={"field": "document_type", "operator": "equals", "value": "invoice"},
        decision=RuleEvaluation.Decision.REQUIRE_APPROVAL,
        reason_codes=["INVOICE_REQUIRES_APPROVAL"],
    )

    result = evaluate_rules({"document_type": "invoice"}, event_id="evt-1")

    assert result.decision == RuleEvaluation.Decision.REQUIRE_APPROVAL
    assert result.rule == rule
    assert result.reason_codes == ["INVOICE_REQUIRES_APPROVAL"]
    assert RuleEvaluation.objects.count() == 1


@pytest.mark.django_db
def test_no_matching_rule_defaults_to_needs_more_data_not_allow():
    Rule.objects.create(
        rule_id="invoice-approval",
        version=1,
        name="Invoice requires approval",
        owner="chief_of_staff",
        status=Rule.Status.ACTIVE,
        conditions={"field": "document_type", "operator": "equals", "value": "invoice"},
        decision=RuleEvaluation.Decision.ALLOW,
    )

    result = evaluate_rules({"document_type": "personal_email"}, event_id="evt-2")

    assert result.decision == RuleEvaluation.Decision.NEEDS_MORE_DATA
    assert result.rule is None
    assert result.reason_codes == ["NO_MATCHING_ACTIVE_RULE"]


@pytest.mark.django_db
def test_draft_rule_is_not_evaluated():
    Rule.objects.create(
        rule_id="draft-allow",
        version=1,
        name="Draft allow",
        owner="chief_of_staff",
        status=Rule.Status.DRAFT,
        conditions={"field": "document_type", "operator": "equals", "value": "invoice"},
        decision=RuleEvaluation.Decision.ALLOW,
    )

    result = evaluate_rules({"document_type": "invoice"}, event_id="evt-3")

    assert result.decision == RuleEvaluation.Decision.NEEDS_MORE_DATA
