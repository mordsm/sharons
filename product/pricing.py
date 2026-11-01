from decimal import Decimal, InvalidOperation

from django.db import transaction

from governance.models import AuditEvent
from portfolio.models import ProjectConnection
from product.models import PricingExperimentBrief, ProductSpecContract
from product.services import InvalidProductContractPayloadError, ProductContractBlockedError
from product.user_research import _looks_like_contact, reject_customer_contact


PAYMENT_FIELD_KEYS = {
    "card_number",
    "charge",
    "customer_id",
    "cvv",
    "pan",
    "payment_provider",
    "publish",
    "refund",
    "spend",
    "spend_money",
    "subscription",
    "webhook",
}


def serialize_pricing_experiment(brief: PricingExperimentBrief) -> dict:
    return {
        "id": str(brief.id),
        "spec_contract_id": str(brief.spec_contract_id),
        "project_id": str(brief.spec_contract.project_id),
        "title": brief.title,
        "hypothesis": brief.hypothesis,
        "success_metric": brief.success_metric,
        "currency": brief.currency,
        "variants": brief.variants,
        "success_criterion": brief.success_criterion,
        "stop_condition": brief.stop_condition,
        "review_status": brief.review_status,
        "no_customer_contact": brief.no_customer_contact,
        "no_external_write": brief.no_external_write,
        "no_payment": brief.no_payment,
        "no_spend": brief.no_spend,
        "created_by": brief.created_by,
        "created_at": brief.created_at.isoformat(),
    }


def _reject_payment_action(payload: dict) -> None:
    reject_customer_contact(payload)
    if payload.get("no_payment") is False or payload.get("no_spend") is False or payload.get("will_charge") is True:
        raise ProductContractBlockedError("A pricing experiment brief cannot charge or spend.")
    for key in PAYMENT_FIELD_KEYS:
        value = payload.get(key)
        if value not in (None, "", [], {}):
            raise ProductContractBlockedError("A pricing experiment brief cannot store a payment or publishing action.")


def _plain_text(value, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise InvalidProductContractPayloadError(f"{field} is required.")
    if _looks_like_contact(text):
        raise ProductContractBlockedError("A pricing experiment brief cannot store a direct contact channel.")
    return text


def _amount(value) -> str:
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise InvalidProductContractPayloadError("Each variant amount must be a decimal amount.")
    if amount != amount.quantize(Decimal("0.01")) or amount <= 0 or amount > Decimal("9999999.99"):
        raise InvalidProductContractPayloadError("Each variant amount must be a positive ILS amount with at most two decimal places.")
    return f"{amount:.2f}"


def _variants(value) -> list[dict]:
    if not isinstance(value, list) or not 2 <= len(value) <= 4:
        raise InvalidProductContractPayloadError("variants must contain two to four prices.")
    variants = []
    labels = []
    for item in value:
        if not isinstance(item, dict):
            raise InvalidProductContractPayloadError("Each variant must be an object.")
        label = _plain_text(item.get("label"), "variant label")
        labels.append(label)
        variants.append({"label": label, "amount": _amount(item.get("amount"))})
    if len(set(labels)) != len(labels):
        raise InvalidProductContractPayloadError("Variant labels must be unique.")
    return variants


def create_pricing_experiment(payload: dict, *, spec_contract_id: str, actor_id: str, correlation_id: str) -> PricingExperimentBrief:
    _reject_payment_action(payload)
    if str(payload.get("currency", "ILS")).strip().upper() != "ILS":
        raise InvalidProductContractPayloadError("currency must be ILS.")
    title = _plain_text(payload.get("title"), "title")
    hypothesis = _plain_text(payload.get("hypothesis"), "hypothesis")
    success_metric = _plain_text(payload.get("success_metric"), "success_metric")
    success_criterion = _plain_text(payload.get("success_criterion"), "success_criterion")
    stop_condition = _plain_text(payload.get("stop_condition"), "stop_condition")
    variants = _variants(payload.get("variants"))

    actor = actor_id.strip() or "api"
    with transaction.atomic():
        spec = ProductSpecContract.objects.select_for_update().select_related("project_connection").get(id=spec_contract_id)
        if spec.status == ProductSpecContract.Status.CANCELLED:
            raise ProductContractBlockedError("A pricing experiment brief requires a product spec that is not cancelled.")
        if spec.project_connection.permission_mode != ProjectConnection.PermissionMode.READ_ONLY or not spec.no_external_write:
            raise ProductContractBlockedError("A pricing experiment brief requires a read-only product spec.")
        brief = PricingExperimentBrief.objects.create(
            spec_contract=spec,
            title=title,
            hypothesis=hypothesis,
            success_metric=success_metric,
            currency="ILS",
            variants=variants,
            success_criterion=success_criterion,
            stop_condition=stop_condition,
            created_by=actor,
        )
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="product.pricing_experiment.created",
            object_type="product.PricingExperimentBrief",
            object_id=str(brief.id),
            correlation_id=correlation_id,
            metadata={
                "spec_contract_id": str(spec.id),
                "project_id": str(spec.project_id),
                "currency": "ILS",
                "no_customer_contact": True,
                "no_external_write": True,
                "no_payment": True,
                "no_spend": True,
            },
        )
    return brief


def review_pricing_experiment(payload: dict, *, brief_id: str, actor_id: str, correlation_id: str) -> PricingExperimentBrief:
    _reject_payment_action(payload)
    decision = str(payload.get("decision", "")).strip()
    if decision not in {PricingExperimentBrief.ReviewStatus.APPROVED, PricingExperimentBrief.ReviewStatus.REJECTED}:
        raise InvalidProductContractPayloadError("decision must be APPROVED or REJECTED.")
    actor = actor_id.strip() or "api"
    with transaction.atomic():
        brief = PricingExperimentBrief.objects.select_for_update().select_related("spec_contract").get(id=brief_id)
        if brief.review_status != PricingExperimentBrief.ReviewStatus.NEEDS_REVIEW:
            raise ProductContractBlockedError("Only pricing experiment briefs that need review can be reviewed.")
        brief.review_status = decision
        brief.save(update_fields=["review_status"])
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="product.pricing_experiment.reviewed",
            object_type="product.PricingExperimentBrief",
            object_id=str(brief.id),
            correlation_id=correlation_id,
            metadata={
                "decision": decision,
                "spec_contract_id": str(brief.spec_contract_id),
                "no_payment": True,
                "no_spend": True,
                "no_external_write": True,
            },
        )
    return brief
