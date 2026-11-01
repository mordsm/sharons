from django.db import transaction

from governance.models import AuditEvent
from portfolio.models import ProjectConnection
from product.models import CompetitiveAnalysisDraft, ProductSpecContract
from product.services import InvalidProductContractPayloadError, ProductContractBlockedError
from product.user_research import reject_customer_contact


def serialize_competitive_analysis(draft: CompetitiveAnalysisDraft) -> dict:
    return {
        "id": str(draft.id),
        "spec_contract_id": str(draft.spec_contract_id),
        "project_id": str(draft.spec_contract.project_id),
        "title": draft.title,
        "competitor_label": draft.competitor_label,
        "comparison_points": draft.comparison_points,
        "implications": draft.implications,
        "review_status": draft.review_status,
        "no_customer_contact": draft.no_customer_contact,
        "no_external_write": draft.no_external_write,
        "created_by": draft.created_by,
        "created_at": draft.created_at.isoformat(),
    }


def _comparison_points(value) -> list[dict]:
    if not isinstance(value, list) or not value:
        raise InvalidProductContractPayloadError("comparison_points must be a non-empty list.")
    points = []
    for item in value:
        if not isinstance(item, dict):
            raise InvalidProductContractPayloadError("Each comparison point must be an object.")
        dimension = str(item.get("dimension", "")).strip()
        observation = str(item.get("observation", "")).strip()
        if not dimension or not observation:
            raise InvalidProductContractPayloadError("Each comparison point requires dimension and observation.")
        points.append({"dimension": dimension, "observation": observation})
    return points


def create_competitive_analysis(payload: dict, *, spec_contract_id: str, actor_id: str, correlation_id: str) -> CompetitiveAnalysisDraft:
    reject_customer_contact(payload)
    title = str(payload.get("title", "")).strip()
    competitor_label = str(payload.get("competitor_label", "")).strip()
    implications = str(payload.get("implications", "")).strip()
    points = _comparison_points(payload.get("comparison_points"))
    if not title or not competitor_label or not implications:
        raise InvalidProductContractPayloadError("title, competitor_label and implications are required.")

    actor = actor_id.strip() or "api"
    with transaction.atomic():
        spec = ProductSpecContract.objects.select_for_update().select_related("project_connection").get(id=spec_contract_id)
        if spec.status == ProductSpecContract.Status.CANCELLED:
            raise ProductContractBlockedError("Competitive analysis requires a product spec that is not cancelled.")
        if spec.project_connection.permission_mode != ProjectConnection.PermissionMode.READ_ONLY or not spec.no_external_write:
            raise ProductContractBlockedError("Competitive analysis requires a read-only product spec.")
        draft = CompetitiveAnalysisDraft.objects.create(
            spec_contract=spec,
            title=title,
            competitor_label=competitor_label,
            comparison_points=points,
            implications=implications,
            created_by=actor,
        )
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="product.competitive_analysis.created",
            object_type="product.CompetitiveAnalysisDraft",
            object_id=str(draft.id),
            correlation_id=correlation_id,
            metadata={
                "spec_contract_id": str(spec.id),
                "project_id": str(spec.project_id),
                "no_customer_contact": True,
                "no_external_write": True,
            },
        )
    return draft


def review_competitive_analysis(payload: dict, *, draft_id: str, actor_id: str, correlation_id: str) -> CompetitiveAnalysisDraft:
    reject_customer_contact(payload)
    decision = str(payload.get("decision", "")).strip()
    if decision not in {CompetitiveAnalysisDraft.ReviewStatus.APPROVED, CompetitiveAnalysisDraft.ReviewStatus.REJECTED}:
        raise InvalidProductContractPayloadError("decision must be APPROVED or REJECTED.")
    actor = actor_id.strip() or "api"
    with transaction.atomic():
        draft = CompetitiveAnalysisDraft.objects.select_for_update().select_related("spec_contract").get(id=draft_id)
        if draft.review_status != CompetitiveAnalysisDraft.ReviewStatus.NEEDS_REVIEW:
            raise ProductContractBlockedError("Only competitive analyses that need review can be reviewed.")
        draft.review_status = decision
        draft.save(update_fields=["review_status"])
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="product.competitive_analysis.reviewed",
            object_type="product.CompetitiveAnalysisDraft",
            object_id=str(draft.id),
            correlation_id=correlation_id,
            metadata={"decision": decision, "spec_contract_id": str(draft.spec_contract_id), "no_external_write": True},
        )
    return draft
