from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from governance.models import AuditEvent
from marketing.models import (
    ContentCalendarItem,
    MarketingArtifact,
    MarketingClaim,
    MarketingExperiment,
    MarketingRequest,
    MarketingReview,
)
from portfolio.models import Objective, Project
from product.models import ProductSpecContract


class MarketingError(Exception):
    code = "MARKETING_ERROR"


class InvalidMarketingPayloadError(MarketingError):
    code = "INVALID_MARKETING_PAYLOAD"


class MarketingBlockedError(MarketingError):
    code = "MARKETING_BLOCKED"


class MarketingAccessDeniedError(MarketingBlockedError):
    code = "MARKETING_ACCESS_DENIED"


PERMISSIONS = {
    "registry_enabled": True,
    "workflow_enabled": True,
    "internal_artifact_write_enabled": True,
    "internal_task_proposal_enabled": True,
    "external_research_enabled": False,
    "analytics_read_enabled": False,
    "crm_read_enabled": False,
    "crm_write_enabled": False,
    "external_write_enabled": False,
    "external_action_enabled": False,
    "email_send_enabled": False,
    "social_publish_enabled": False,
    "ads_manage_enabled": False,
    "ad_spend_enabled": False,
}

INJECTION_MARKERS = ("ignore previous", "ignore all instructions", "ignore guardrails", "disregard the rules", "you are now")
FORBIDDEN_INPUT_KEYS = {"crm_contacts", "contact_list", "customer_emails", "ad_account_id"}


def marketing_status() -> dict:
    from operations.models import AgentDefinition, AgentRun

    agent = AgentDefinition.objects.filter(agent_id="marketing", active=True).first()
    last_run = AgentRun.objects.filter(agent_id="marketing").order_by("-started_at").first()
    return {
        "agent_id": "marketing",
        "agent_registered": agent is not None,
        "runner_enabled": True,
        "operative": agent is not None,
        "last_run_status": last_run.status if last_run else "",
        "permissions": PERMISSIONS,
        "connectors": {"analytics": "NOT_CONNECTED", "crm": "NOT_CONNECTED", "ads": "NOT_CONNECTED", "social": "NOT_CONNECTED"},
        "live_data": False,
        "request_count": MarketingRequest.objects.count(),
        "artifact_count": MarketingArtifact.objects.count(),
        "pending_reviews": MarketingArtifact.objects.filter(status=MarketingArtifact.Status.DRAFT).count(),
        "calendar_count": ContentCalendarItem.objects.count(),
        "experiment_count": MarketingExperiment.objects.count(),
        "claims_needing_review": MarketingClaim.objects.filter(review_status=MarketingClaim.ReviewStatus.NEEDS_REVIEW).count(),
        "external_action_enabled": False,
    }


def create_marketing_request(payload: dict, *, actor_id: str, correlation_id: str) -> MarketingRequest:
    actor = actor_id.strip() or "api"
    correlation = correlation_id.strip()
    if not correlation:
        raise InvalidMarketingPayloadError("correlation_id is required.")
    _reject_forbidden_inputs(payload, actor=actor, correlation=correlation)
    objective_text, ignored_instruction = _objective_text(payload)
    requested_action = str(payload.get("requested_action", "STRATEGY")).strip().upper() or "STRATEGY"
    if requested_action not in {"STRATEGY", "PUBLISH", "SPEND", "CAMPAIGN"}:
        raise InvalidMarketingPayloadError("requested_action must be STRATEGY, CAMPAIGN, PUBLISH, or SPEND.")
    project = _project(payload.get("project_id"))
    objective_record, dependency_blocked = _objective(payload.get("objective_id"))
    geography = _string_list(payload.get("geography", []))
    audiences = _string_list(payload.get("audiences", []))
    constraints = _string_list(payload.get("constraints", []))
    sources = _sources(payload.get("sources", []))
    budget_amount, currency = _budget(payload)
    time_horizon = str(payload.get("time_horizon", "30 days")).strip() or "30 days"
    _dates(payload)
    features = _known_features(project)
    asks_share = _asks_for_share(payload, objective_text)
    has_share_evidence = any(item.get("kind") == "market_share" for item in sources)

    if not objective_text:
        return _store_request(
            project=project,
            objective_record=objective_record,
            objective_text="",
            geography=geography,
            audiences=audiences,
            budget_amount=budget_amount,
            currency=currency,
            time_horizon=time_horizon,
            constraints=constraints,
            sources=sources,
            inputs=payload.get("inputs", {}) if isinstance(payload.get("inputs"), dict) else {},
            status=MarketingRequest.Status.NEEDS_INPUT,
            summary="The marketing objective is missing.",
            assumptions=["No plan was generated because the objective was empty."],
            risks=["A plan without an objective would invent a market."],
            actor=actor,
            correlation=correlation,
            artifacts=[],
            ignored_instruction=ignored_instruction,
        )

    assumptions = []
    risks = [
        "No external research connector is enabled. Competitor and market figures are not available.",
        "Draft copy is not approved for publication.",
        "A small sample cannot support a significance claim.",
    ]
    if not features:
        assumptions.append("Product features were not supplied. No feature claims are included.")
    if not sources:
        assumptions.append("No customer research source was supplied. Audience statements are hypotheses.")
    if not audiences:
        assumptions.append("No audience evidence was supplied. The ICP below is a hypothesis, not a validated segment.")
    if ignored_instruction:
        assumptions.append("Untrusted text asked to bypass marketing guardrails. That text was ignored.")

    if asks_share and not has_share_evidence:
        content = {
            "market_share": None,
            "known": False,
            "label": "UNKNOWN",
            "proposed_research": "Collect a sourced market or competitor note before any share figure is used.",
            "live_data": False,
        }
        return _store_request(
            project=project,
            objective_record=objective_record,
            objective_text=objective_text,
            geography=geography,
            audiences=audiences,
            budget_amount=budget_amount,
            currency=currency,
            time_horizon=time_horizon,
            constraints=constraints,
            sources=sources,
            inputs=_inputs(payload),
            status=MarketingRequest.Status.INSUFFICIENT_EVIDENCE,
            summary="Competitor or market share was requested without a source. No figure was created.",
            assumptions=assumptions,
            risks=risks,
            actor=actor,
            correlation=correlation,
            artifacts=[
                _artifact_spec(
                    MarketingArtifact.ArtifactType.STRATEGY,
                    "Market share is unknown.",
                    content,
                    assumptions,
                    risks,
                    [],
                )
            ],
            ignored_instruction=ignored_instruction,
            dependency_blocked=dependency_blocked,
        )

    plan = _plan(
        objective_text=objective_text,
        geography=geography,
        audiences=audiences,
        features=features,
        budget_amount=budget_amount,
        currency=currency,
        time_horizon=time_horizon,
        sources=sources,
        requested_action=requested_action,
    )
    status = MarketingRequest.Status.BLOCKED_DEPENDENCY if dependency_blocked else MarketingRequest.Status.COMPLETED_DRAFT
    if dependency_blocked:
        risks.append("The linked objective is not an active objective, so the project-manager handoff was not created.")
    return _store_request(
        project=project,
        objective_record=objective_record,
        objective_text=objective_text,
        geography=geography,
        audiences=audiences,
        budget_amount=budget_amount,
        currency=currency,
        time_horizon=time_horizon,
        constraints=constraints,
        sources=sources,
        inputs=_inputs(payload),
        status=status,
        summary=plan["summary"],
        assumptions=assumptions + plan["assumptions"],
        risks=risks,
        actor=actor,
        correlation=correlation,
        artifacts=plan["artifacts"],
        ignored_instruction=ignored_instruction,
        dependency_blocked=dependency_blocked,
        handoff=not dependency_blocked and objective_record is not None,
    )


def create_campaign_brief(payload: dict, *, request_id: str, actor_id: str, correlation_id: str) -> MarketingArtifact:
    channel = str(payload.get("channel", "manual_draft")).strip() or "manual_draft"
    if channel.lower() in {"publish", "send", "ads_live"}:
        raise MarketingBlockedError("Campaign briefs stay drafts. Publishing and sending are disabled.")
    actor = actor_id.strip() or "api"
    with transaction.atomic():
        marketing_request = MarketingRequest.objects.select_for_update().get(id=request_id)
        if not marketing_request.artifacts.filter(artifact_type=MarketingArtifact.ArtifactType.STRATEGY).exists():
            raise MarketingBlockedError("A strategy draft is required before a campaign brief.")
        version = marketing_request.artifacts.filter(artifact_type=MarketingArtifact.ArtifactType.CAMPAIGN_BRIEF).count() + 1
        artifact = MarketingArtifact.objects.create(
            request=marketing_request,
            artifact_type=MarketingArtifact.ArtifactType.CAMPAIGN_BRIEF,
            version=version,
            summary=f"Draft {channel} brief for manual use only.",
            content={
                "channel": channel,
                "label": "DRAFT",
                "goal": marketing_request.objective_text,
                "budget_cap": _money(marketing_request.budget_amount, marketing_request.currency),
                "assets": _copy_variants(marketing_request.objective_text),
                "tracking": _tracking_plan(),
                "will_publish": False,
            },
            evidence=marketing_request.sources,
            assumptions=marketing_request.assumptions,
            risks=marketing_request.risks,
            claims=[{"text": marketing_request.objective_text, "supported": False, "reason": "Objective text is not proof."}],
            owner="marketing",
        )
        _audit("marketing.artifact_created", artifact, actor, correlation_id, {"artifact_type": artifact.artifact_type, "version": version})
    return artifact


def review_artifact(payload: dict, *, artifact_id: str, actor_id: str, correlation_id: str) -> MarketingArtifact:
    decision = str(payload.get("decision", "")).strip().upper()
    if decision not in MarketingReview.Decision.values:
        raise InvalidMarketingPayloadError("decision must be APPROVED, REJECTED, or CHANGES_REQUESTED.")
    acknowledge = bool(payload.get("acknowledge_unsupported_claims", False))
    actor = actor_id.strip() or "api"
    with transaction.atomic():
        artifact = MarketingArtifact.objects.select_for_update().get(id=artifact_id)
        unsupported = [claim for claim in artifact.claims if not claim.get("supported")]
        if decision == MarketingReview.Decision.APPROVED and unsupported and not acknowledge:
            raise MarketingBlockedError("Unsupported claims must be acknowledged before manual-use approval.")
        status_for = {
            MarketingReview.Decision.APPROVED: MarketingArtifact.Status.APPROVED_FOR_MANUAL_USE,
            MarketingReview.Decision.REJECTED: MarketingArtifact.Status.REJECTED,
            MarketingReview.Decision.CHANGES_REQUESTED: MarketingArtifact.Status.IN_REVIEW,
        }
        artifact.status = status_for[decision]
        artifact.save(update_fields=["status"])
        MarketingReview.objects.create(
            artifact=artifact,
            artifact_version=artifact.version,
            decision=decision,
            reason=str(payload.get("reason", "")).strip(),
            approver=actor,
        )
        _audit("marketing.review_decided", artifact, actor, correlation_id, {"decision": decision, "version": artifact.version})
    return artifact


def create_calendar_item(payload: dict, *, request_id: str, actor_id: str, correlation_id: str) -> ContentCalendarItem:
    _reject_external_flags(payload, publish=True, send=True, spend=False)
    title = _required_text(payload.get("title"), "title")
    body = _required_text(payload.get("body"), "body")
    channel = str(payload.get("channel", "")).strip().upper()
    if channel not in ContentCalendarItem.Channel.values:
        raise InvalidMarketingPayloadError("channel must be LANDING_DRAFT, EMAIL_DRAFT, or SOCIAL_DRAFT.")
    planned_on = _planned_on(payload.get("planned_on"))
    actor = actor_id.strip() or "api"
    correlation = correlation_id.strip()
    if not correlation:
        raise InvalidMarketingPayloadError("correlation_id is required.")
    with transaction.atomic():
        marketing_request = MarketingRequest.objects.select_for_update().get(id=request_id)
        item = ContentCalendarItem.objects.create(
            request=marketing_request,
            title=title,
            channel=channel,
            planned_on=planned_on,
            body=body,
            created_by=actor,
            correlation_id=correlation,
        )
        _audit("marketing.calendar_item_created", item, actor, correlation, {"channel": channel, "will_publish": False, "will_send": False})
    return item


def review_calendar_item(payload: dict, *, item_id: str, actor_id: str, correlation_id: str) -> ContentCalendarItem:
    _reject_external_flags(payload, publish=True, send=True, spend=False)
    decision = str(payload.get("decision", "")).strip().upper()
    if decision not in {ContentCalendarItem.Status.ACKNOWLEDGED, ContentCalendarItem.Status.REJECTED}:
        raise InvalidMarketingPayloadError("decision must be ACKNOWLEDGED or REJECTED.")
    actor = actor_id.strip() or "api"
    with transaction.atomic():
        item = ContentCalendarItem.objects.select_for_update().get(id=item_id)
        if item.status != ContentCalendarItem.Status.DRAFT:
            raise MarketingBlockedError("This calendar item was already reviewed.")
        item.status = decision
        item.save(update_fields=["status", "title", "body", "created_by", "correlation_id", "will_publish", "will_send"])
        _audit("marketing.calendar_item_reviewed", item, actor, correlation_id, {"decision": decision, "will_publish": False, "will_send": False})
    return item


def create_experiment(payload: dict, *, request_id: str, actor_id: str, correlation_id: str) -> MarketingExperiment:
    _reject_external_flags(payload, publish=False, send=False, spend=True)
    _reject_significance(payload)
    hypothesis = _required_text(payload.get("hypothesis"), "hypothesis")
    metric = _required_text(payload.get("metric"), "metric")
    notes = str(payload.get("notes", "")).strip()
    sample_size = _optional_sample_size(payload.get("sample_size"))
    actor = actor_id.strip() or "api"
    correlation = correlation_id.strip()
    if not correlation:
        raise InvalidMarketingPayloadError("correlation_id is required.")
    with transaction.atomic():
        marketing_request = MarketingRequest.objects.select_for_update().get(id=request_id)
        experiment = MarketingExperiment.objects.create(
            request=marketing_request,
            hypothesis=hypothesis,
            metric=metric,
            notes=notes,
            sample_size=sample_size,
            created_by=actor,
            correlation_id=correlation,
        )
        _audit(
            "marketing.experiment_registered",
            experiment,
            actor,
            correlation,
            {"will_spend": False, "significance_claimed": False},
        )
    return experiment


def review_experiment(payload: dict, *, experiment_id: str, actor_id: str, correlation_id: str) -> MarketingExperiment:
    _reject_external_flags(payload, publish=False, send=False, spend=True)
    _reject_significance(payload)
    decision = str(payload.get("decision", "")).strip().upper()
    if decision not in {MarketingExperiment.Status.ACKNOWLEDGED, MarketingExperiment.Status.REJECTED}:
        raise InvalidMarketingPayloadError("decision must be ACKNOWLEDGED or REJECTED.")
    actor = actor_id.strip() or "api"
    with transaction.atomic():
        experiment = MarketingExperiment.objects.select_for_update().get(id=experiment_id)
        if experiment.status != MarketingExperiment.Status.PROPOSED:
            raise MarketingBlockedError("This experiment was already reviewed.")
        experiment.status = decision
        experiment.save(update_fields=["status", "hypothesis", "metric", "notes", "created_by", "correlation_id", "will_spend", "significance_claimed"])
        _audit("marketing.experiment_reviewed", experiment, actor, correlation_id, {"decision": decision, "will_spend": False})
    return experiment


def create_claim(payload: dict, *, request_id: str, actor_id: str, correlation_id: str) -> MarketingClaim:
    text = _required_text(payload.get("text"), "text")
    _reject_claim_instruction(text, actor_id, correlation_id)
    evidence_note = str(payload.get("evidence_note", "")).strip()
    supported = bool(payload.get("supported", False))
    if supported and not evidence_note:
        raise MarketingBlockedError("A claim cannot be marked supported without an evidence note.")
    actor = actor_id.strip() or "api"
    correlation = correlation_id.strip()
    if not correlation:
        raise InvalidMarketingPayloadError("correlation_id is required.")
    with transaction.atomic():
        marketing_request = MarketingRequest.objects.select_for_update().get(id=request_id)
        claim = MarketingClaim.objects.create(
            request=marketing_request,
            text=text,
            evidence_note=evidence_note,
            supported=supported,
            created_by=actor,
            correlation_id=correlation,
        )
        _audit("marketing.claim_registered", claim, actor, correlation, {"supported": claim.supported})
    return claim


def review_claim(payload: dict, *, claim_id: str, actor_id: str, correlation_id: str) -> MarketingClaim:
    decision = str(payload.get("decision", "")).strip().upper()
    if decision not in {"ACCEPT", "ACKNOWLEDGE_UNSUPPORTED", "REJECT"}:
        raise InvalidMarketingPayloadError("decision must be ACCEPT, ACKNOWLEDGE_UNSUPPORTED, or REJECT.")
    actor = actor_id.strip() or "api"
    evidence_note = str(payload.get("evidence_note", "")).strip()
    with transaction.atomic():
        claim = MarketingClaim.objects.select_for_update().get(id=claim_id)
        if claim.review_status != MarketingClaim.ReviewStatus.NEEDS_REVIEW:
            raise MarketingBlockedError("This claim was already reviewed.")
        if decision == "ACCEPT":
            note = evidence_note or claim.evidence_note
            if not note:
                raise MarketingBlockedError("A claim cannot be accepted without an evidence note.")
            claim.evidence_note = note
            claim.supported = True
            claim.review_status = MarketingClaim.ReviewStatus.ACCEPTED
        elif decision == "ACKNOWLEDGE_UNSUPPORTED":
            if not payload.get("acknowledge_unsupported"):
                raise MarketingBlockedError("Unsupported claims must be explicitly acknowledged.")
            claim.supported = False
            claim.review_status = MarketingClaim.ReviewStatus.ACKNOWLEDGED_UNSUPPORTED
        else:
            claim.review_status = MarketingClaim.ReviewStatus.REJECTED
        claim.save()
        _audit(
            "marketing.claim_reviewed",
            claim,
            actor,
            correlation_id,
            {"decision": decision, "supported": claim.supported, "review_status": claim.review_status},
        )
    return claim


def revise_artifact(payload: dict, *, artifact_id: str, actor_id: str, correlation_id: str) -> MarketingArtifact:
    summary = str(payload.get("summary", "")).strip()
    content = payload.get("content")
    if content is not None and not isinstance(content, dict):
        raise InvalidMarketingPayloadError("content must be an object.")
    actor = actor_id.strip() or "api"
    with transaction.atomic():
        current = MarketingArtifact.objects.select_for_update().get(id=artifact_id)
        latest = (
            MarketingArtifact.objects.select_for_update()
            .filter(request=current.request, artifact_type=current.artifact_type)
            .order_by("-version")
            .first()
        )
        revised = MarketingArtifact.objects.create(
            request=current.request,
            artifact_type=current.artifact_type,
            version=latest.version + 1,
            summary=summary or latest.summary,
            content=content if content is not None else latest.content,
            evidence=latest.evidence,
            assumptions=latest.assumptions,
            risks=latest.risks,
            claims=latest.claims,
            owner=actor,
        )
        _audit("marketing.artifact_created", revised, actor, correlation_id, {"version": revised.version, "previous_version": latest.version})
    return revised


def analyze_performance(payload: dict, *, actor_id: str, correlation_id: str) -> MarketingRequest:
    actor = actor_id.strip() or "api"
    correlation = correlation_id.strip()
    if not correlation:
        raise InvalidMarketingPayloadError("correlation_id is required.")
    _reject_forbidden_inputs(payload, actor=actor, correlation=correlation)
    if payload.get("use_live_connector"):
        raise MarketingBlockedError("Analytics, CRM, and ad connectors are not connected.")
    metric = str(payload.get("metric", "")).strip()
    if not metric:
        raise InvalidMarketingPayloadError("metric is required.")
    denominator = payload.get("denominator")
    numerator = payload.get("numerator")
    rate = None
    status = MarketingRequest.Status.COMPLETED_DRAFT
    summary = "Performance notes use only the supplied snapshot. This is not live data."
    if metric == "conversion_rate" and not _positive_number(denominator):
        status = MarketingRequest.Status.INSUFFICIENT_EVIDENCE
        summary = "Conversion rate was not calculated because the denominator is missing."
    elif _positive_number(denominator) and _number(numerator) is not None:
        rate = float(_number(numerator)) / float(_number(denominator))
        summary = "Conversion rate was calculated from the supplied snapshot only."
    return _store_request(
        project=_project(payload.get("project_id")),
        objective_record=None,
        objective_text=str(payload.get("objective", "Performance review")).strip() or "Performance review",
        geography=[],
        audiences=[],
        budget_amount=None,
        currency="",
        time_horizon=str(payload.get("time_horizon", "supplied snapshot")),
        constraints=[],
        sources=_sources(payload.get("sources", [])),
        inputs={"metric": metric, "numerator": numerator, "denominator": denominator, "simulated": bool(payload.get("simulated", False))},
        status=status,
        summary=summary,
        assumptions=["No analytics connector was used."],
        risks=["A rate without a denominator would misstate performance."],
        actor=actor,
        correlation=correlation,
        artifacts=[
            _artifact_spec(
                MarketingArtifact.ArtifactType.PERFORMANCE_REPORT,
                summary,
                {"metric": metric, "numerator": numerator, "denominator": denominator, "rate": rate, "live_data": False, "simulated": bool(payload.get("simulated", False))},
                ["No analytics connector was used."],
                ["Do not treat this snapshot as a live dashboard."],
                [],
            )
        ],
        ignored_instruction=False,
    )


def decision_summary(request_id: str) -> dict:
    marketing_request = MarketingRequest.objects.get(id=request_id)
    artifacts = list(marketing_request.artifacts.all())
    return {
        "request_id": str(marketing_request.id),
        "owner": "chief_of_staff",
        "recommendation": marketing_request.summary,
        "evidence": marketing_request.sources,
        "options": ["Approve the draft for manual execution.", "Request customer interviews before any message test.", "Stop and collect the missing source."],
        "risks": marketing_request.risks,
        "assumptions": marketing_request.assumptions,
        "artifacts": [serialize_artifact(artifact) for artifact in artifacts],
        "external_action_enabled": False,
    }


def serialize_request(marketing_request: MarketingRequest) -> dict:
    return {
        "id": str(marketing_request.id),
        "project_id": str(marketing_request.project_id) if marketing_request.project_id else None,
        "objective_id": str(marketing_request.objective_record_id) if marketing_request.objective_record_id else None,
        "objective": marketing_request.objective_text,
        "status": marketing_request.status,
        "summary": marketing_request.summary,
        "geography": marketing_request.geography,
        "audiences": marketing_request.audiences,
        "budget_amount": str(marketing_request.budget_amount) if marketing_request.budget_amount is not None else None,
        "currency": marketing_request.currency,
        "time_horizon": marketing_request.time_horizon,
        "assumptions": marketing_request.assumptions,
        "risks": marketing_request.risks,
        "sources": marketing_request.sources,
        "permissions": PERMISSIONS,
        "external_action_enabled": False,
        "social_publish_enabled": False,
        "email_send_enabled": False,
        "ad_spend_enabled": False,
        "correlation_id": marketing_request.correlation_id,
        "created_at": marketing_request.created_at.isoformat(),
        "artifacts": [serialize_artifact(artifact) for artifact in marketing_request.artifacts.all()],
        "calendar_items": [serialize_calendar_item(item) for item in marketing_request.calendar_items.all()],
        "experiments": [serialize_experiment(item) for item in marketing_request.experiments.all()],
        "claims_register": [serialize_claim(item) for item in marketing_request.claims.all()],
    }


def serialize_calendar_item(item: ContentCalendarItem) -> dict:
    return {
        "id": str(item.id),
        "request_id": str(item.request_id),
        "title": item.title,
        "channel": item.channel,
        "planned_on": item.planned_on.isoformat(),
        "body": item.body,
        "status": item.status,
        "will_publish": False,
        "will_send": False,
        "created_at": item.created_at.isoformat(),
    }


def serialize_experiment(experiment: MarketingExperiment) -> dict:
    return {
        "id": str(experiment.id),
        "request_id": str(experiment.request_id),
        "hypothesis": experiment.hypothesis,
        "metric": experiment.metric,
        "notes": experiment.notes,
        "sample_size": experiment.sample_size,
        "status": experiment.status,
        "will_spend": False,
        "significance_claimed": False,
        "created_at": experiment.created_at.isoformat(),
    }


def serialize_claim(claim: MarketingClaim) -> dict:
    return {
        "id": str(claim.id),
        "request_id": str(claim.request_id),
        "text": claim.text,
        "evidence_note": claim.evidence_note,
        "supported": claim.supported,
        "review_status": claim.review_status,
        "created_at": claim.created_at.isoformat(),
    }


def serialize_artifact(artifact: MarketingArtifact) -> dict:
    reviews = [
        {"decision": review.decision, "version": review.artifact_version, "approver": review.approver, "reason": review.reason}
        for review in artifact.reviews.all()
    ]
    return {
        "id": str(artifact.id),
        "request_id": str(artifact.request_id),
        "artifact_type": artifact.artifact_type,
        "version": artifact.version,
        "status": artifact.status,
        "summary": artifact.summary,
        "content": artifact.content,
        "evidence": artifact.evidence,
        "assumptions": artifact.assumptions,
        "risks": artifact.risks,
        "claims": artifact.claims,
        "approval_required": artifact.status != MarketingArtifact.Status.APPROVED_FOR_MANUAL_USE,
        "reviews": reviews,
        "no_external_action": True,
        "created_at": artifact.created_at.isoformat(),
    }


def _store_request(**kwargs) -> MarketingRequest:
    actor = kwargs["actor"]
    correlation = kwargs["correlation"]
    with transaction.atomic():
        marketing_request = MarketingRequest.objects.create(
            project=kwargs["project"],
            objective_record=kwargs["objective_record"],
            objective_text=kwargs["objective_text"],
            geography=kwargs["geography"],
            audiences=kwargs["audiences"],
            budget_amount=kwargs["budget_amount"],
            currency=kwargs["currency"],
            time_horizon=kwargs["time_horizon"],
            constraints=kwargs["constraints"],
            sources=kwargs["sources"],
            inputs=kwargs["inputs"] if isinstance(kwargs["inputs"], dict) else {},
            status=kwargs["status"],
            summary=kwargs["summary"],
            assumptions=kwargs["assumptions"],
            risks=kwargs["risks"],
            correlation_id=correlation,
            created_by=actor,
        )
        _audit("marketing.requested", marketing_request, actor, correlation, {"status": marketing_request.status})
        if kwargs["ignored_instruction"]:
            _audit("marketing.untrusted_instruction_ignored", marketing_request, actor, correlation, {"applied": False})
        for spec in kwargs["artifacts"]:
            artifact = MarketingArtifact.objects.create(request=marketing_request, owner="marketing", **spec)
            _audit("marketing.artifact_created", artifact, actor, correlation, {"artifact_type": artifact.artifact_type})
        if kwargs.get("dependency_blocked"):
            _audit("marketing.blocked", marketing_request, actor, correlation, {"reason": "BLOCKED_DEPENDENCY"})
        if kwargs.get("handoff"):
            from project_manager.services import propose_milestones

            propose_milestones(
                {
                    "milestones": [
                        {
                            "key": f"marketing-review-{marketing_request.id}",
                            "title": "Review the marketing draft before any manual execution",
                            "rationale": marketing_request.summary,
                        }
                    ]
                },
                objective_id=str(marketing_request.objective_record_id),
                actor_id=actor,
                correlation_id=correlation,
            )
    return marketing_request


def _plan(*, objective_text, geography, audiences, features, budget_amount, currency, time_horizon, sources, requested_action) -> dict:
    audience = audiences[0] if audiences else "the stated segment"
    place = ", ".join(geography) if geography else "the stated geography"
    claims = [{"text": feature, "supported": True, "reason": "Taken from an internal product spec."} for feature in features]
    claims.append({"text": objective_text, "supported": bool(sources), "reason": "Supported only when a source is attached."})
    message_a = f"Draft hypothesis A for {audience}: lead with the job in the objective, and name only these features: {features or ['none supplied']}."
    message_b = f"Draft hypothesis B for {place}: lead with the cost of the current workaround. Do not claim results that are not in the sources."
    handoff = requested_action in {"PUBLISH", "SPEND"}
    summary = "30-day draft plan. Nothing will be published or purchased."
    if requested_action == "PUBLISH":
        summary = "Publication was refused. A manual handoff draft was saved instead."
    if requested_action == "SPEND":
        summary = "No ad account was changed. The amount below is a proposed cap only."
    artifacts = [
        _artifact_spec(MarketingArtifact.ArtifactType.ICP, "Provisional audience hypothesis.", {"hypotheses": [f"{audience} in {place}"], "validated": False, "missing": ["customer interviews"]}, [], [], claims),
        _artifact_spec(MarketingArtifact.ArtifactType.POSITIONING, "Two message hypotheses.", {"messages": [message_a, message_b], "proof_required": ["A customer quote or product spec for every claim."]}, [], [], claims),
        _artifact_spec(
            MarketingArtifact.ArtifactType.STRATEGY,
            summary,
            {
                "channels": [
                    {"name": "customer_interviews", "rank": 1, "reason": "No validated research was supplied, so learning comes before distribution.", "chosen": True},
                    {"name": "manual_content_drafts", "rank": 2, "reason": "Copy can be prepared internally without publishing.", "chosen": True},
                    {"name": "paid_ads", "rank": 3, "reason": "Listed only as a proposed cap. Ad spending is disabled.", "chosen": False},
                ],
                "plan": [
                    {"week": 1, "owner": "marketing", "work": "Write interview questions and list missing proof."},
                    {"week": 2, "owner": "marketing", "work": "Draft two messages and a landing outline."},
                    {"week": 3, "owner": "human approver", "work": "Decide whether a manual test is allowed. Do not publish from Sharons."},
                    {"week": 4, "owner": "chief_of_staff", "work": "Review what was learned. Do not call a small sample significant."},
                ],
                "budget": {"amount": str(budget_amount) if budget_amount is not None else None, "currency": currency, "kind": "PROPOSED", "will_spend": False},
                "kpi_tree": {"north_star": "selected per objective", "values": None, "label": "NOT_MEASURED"},
                "time_horizon": time_horizon,
                "live_data": False,
            },
            [],
            [],
            claims,
        ),
        _artifact_spec(
            MarketingArtifact.ArtifactType.CAMPAIGN_BRIEF,
            "Draft campaign brief for manual use.",
            {"assets": _copy_variants(objective_text), "landing_outline": ["problem", "proof still needed", "invitation to talk"], "tracking": _tracking_plan(), "will_publish": False},
            [],
            [],
            claims,
        ),
        _artifact_spec(
            MarketingArtifact.ArtifactType.DECISION_BUNDLE,
            "Decision needed before any manual execution.",
            {"owner": "chief_of_staff", "recommendation": "Approve interviews and draft review. Do not publish or spend yet.", "options": ["approve manual draft review", "collect interviews first", "stop"]},
            [],
            [],
            [],
        ),
    ]
    if handoff:
        artifacts.append(
            _artifact_spec(
                MarketingArtifact.ArtifactType.MANUAL_HANDOFF,
                "External action refused. A person may execute this only outside Sharons after approval.",
                {"requested_action": requested_action, "will_publish": False, "will_spend": False, "proposed_budget": _money(budget_amount, currency)},
                [],
                [],
                [],
            )
        )
    return {"summary": summary, "assumptions": [], "artifacts": artifacts}


def _artifact_spec(artifact_type, summary, content, assumptions, risks, claims) -> dict:
    return {
        "artifact_type": artifact_type,
        "summary": summary,
        "content": content,
        "assumptions": assumptions,
        "risks": risks,
        "claims": claims,
        "evidence": [],
    }


def _copy_variants(objective_text: str) -> list[dict]:
    return [
        {"label": "DRAFT", "channel": "landing", "text": f"Working draft, not for publication: {objective_text}"},
        {"label": "DRAFT", "channel": "social", "text": "Working draft, not for publication: ask for a conversation. No result is claimed."},
        {"label": "DRAFT", "channel": "search", "text": "Working draft, not for publication: describe the job. Do not state a market share or customer count."},
    ]


def _tracking_plan() -> dict:
    return {"utm": "utm_source / utm_medium / utm_campaign", "conversions": "define numerator and denominator before calculating a rate", "cadence": "weekly review", "live_data": False}


def _known_features(project) -> list[str]:
    if project is None:
        return []
    titles = ProductSpecContract.objects.filter(project=project).exclude(status=ProductSpecContract.Status.CANCELLED).values_list("title", flat=True)
    return [title.strip() for title in titles if title and title.strip()]


def _project(project_id):
    if not project_id:
        return None
    try:
        return Project.objects.get(id=str(project_id).strip())
    except (Project.DoesNotExist, ValidationError, ValueError):
        raise Project.DoesNotExist


def _objective(objective_id):
    if not objective_id:
        return None, False
    try:
        objective = Objective.objects.filter(id=str(objective_id).strip()).first()
    except (ValidationError, ValueError) as exc:
        raise InvalidMarketingPayloadError("objective_id must be a UUID.") from exc
    if objective is None or objective.status != Objective.Status.ACTIVE:
        return None, True
    return objective, False


def _budget(payload):
    raw = payload.get("budget_amount")
    if raw in (None, ""):
        return None, str(payload.get("currency", "")).strip().upper()
    try:
        amount = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise InvalidMarketingPayloadError("budget_amount must be a number.") from exc
    if amount < 0:
        raise InvalidMarketingPayloadError("budget_amount cannot be negative.")
    return amount, str(payload.get("currency", "")).strip().upper()


def _dates(payload) -> None:
    start = str(payload.get("starts_on", "")).strip()
    end = str(payload.get("ends_on", "")).strip()
    if not start or not end:
        return
    try:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
    except ValueError as exc:
        raise InvalidMarketingPayloadError("starts_on and ends_on must be YYYY-MM-DD dates.") from exc
    if end_date < start_date:
        raise InvalidMarketingPayloadError("ends_on cannot be earlier than starts_on.")


def _sources(value) -> list:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise InvalidMarketingPayloadError("sources must be a list.")
    sources = []
    for item in value:
        if not isinstance(item, dict) or not str(item.get("title", "")).strip():
            raise InvalidMarketingPayloadError("Each source needs a title.")
        sources.append(
            {
                "title": str(item.get("title")).strip(),
                "source_type": str(item.get("source_type", "user_supplied")).strip() or "user_supplied",
                "uri_or_internal_ref": str(item.get("uri_or_internal_ref", "")).strip(),
                "confidence": str(item.get("confidence", "low")).strip() or "low",
                "kind": str(item.get("kind", "")).strip(),
            }
        )
    return sources


def _string_list(value) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        raise InvalidMarketingPayloadError("Expected a list of strings.")
    return [str(item).strip() for item in value if str(item).strip()]


def _inputs(payload) -> dict:
    inputs = payload.get("inputs", {})
    return inputs if isinstance(inputs, dict) else {}


def _objective_text(payload) -> tuple[str, bool]:
    raw = str(payload.get("objective", "")).strip()
    extra = payload.get("inputs", {})
    blob = raw
    if isinstance(extra, dict):
        blob = f"{raw}\n{extra.get('notes', '')}"
    ignored = any(marker in blob.lower() for marker in INJECTION_MARKERS)
    lines = [line.strip() for line in raw.splitlines() if line.strip() and not any(marker in line.lower() for marker in INJECTION_MARKERS)]
    return " ".join(lines).strip(), ignored


def _asks_for_share(payload, objective_text: str) -> bool:
    blob = f"{objective_text} {payload.get('question', '')}".lower()
    return "market share" in blob or "competitor share" in blob


def _reject_forbidden_inputs(payload, *, actor: str, correlation: str) -> None:
    classification = str(payload.get("data_classification", "")).strip().upper()
    present = FORBIDDEN_INPUT_KEYS.intersection(payload)
    if classification not in {"PERSONAL_SENSITIVE", "CONFIDENTIAL"} and not present:
        return
    AuditEvent.objects.create(
        actor_type=AuditEvent.ActorType.AGENT,
        actor_id=actor,
        action="marketing.access_denied",
        object_type="marketing.MarketingRequest",
        object_id="access",
        correlation_id=correlation,
        metadata={"external_action": False},
    )
    if present:
        raise MarketingAccessDeniedError("CRM contacts, customer lists, and ad accounts are not available to Marketing.")
    raise MarketingAccessDeniedError("Marketing cannot accept confidential or personal-sensitive inputs.")


def _money(amount, currency) -> dict:
    return {"amount": str(amount) if amount is not None else None, "currency": currency, "kind": "PROPOSED", "will_spend": False}


def _number(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _positive_number(value) -> bool:
    number = _number(value)
    return number is not None and number > 0


def _required_text(value, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise InvalidMarketingPayloadError(f"{field} is required.")
    return text


def _planned_on(value):
    text = str(value or "").strip()
    if not text:
        raise InvalidMarketingPayloadError("planned_on is required.")
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise InvalidMarketingPayloadError("planned_on must be a YYYY-MM-DD date.")


def _reject_external_flags(payload: dict, *, publish: bool, send: bool, spend: bool) -> None:
    if publish and (payload.get("will_publish") is True or payload.get("publish") is True):
        raise MarketingBlockedError("A content calendar item cannot publish.")
    if send and (payload.get("will_send") is True or payload.get("send") is True):
        raise MarketingBlockedError("A content calendar item cannot send.")
    if spend and (payload.get("will_spend") is True or payload.get("spend") is True or payload.get("ad_spend_enabled") is True):
        raise MarketingBlockedError("An experiment register entry cannot spend.")


def _reject_significance(payload: dict) -> None:
    if payload.get("significance_claimed") is True or payload.get("claim_significance") is True or payload.get("statistically_significant") is True:
        raise MarketingBlockedError("An experiment register entry cannot claim statistical significance.")
    if payload.get("p_value") not in (None, ""):
        raise MarketingBlockedError("An experiment register entry cannot store a p-value.")


def _optional_sample_size(value):
    if value in (None, ""):
        return None
    number = _number(value)
    if number is None or number != int(number) or number <= 0:
        raise InvalidMarketingPayloadError("sample_size must be a positive integer when supplied.")
    return int(number)


def _reject_claim_instruction(text: str, actor_id: str, correlation_id: str) -> None:
    lowered = text.lower()
    if any(marker in lowered for marker in INJECTION_MARKERS):
        _audit_unscoped(actor_id, correlation_id, "marketing.untrusted_claim_ignored")
        raise MarketingBlockedError("Untrusted instructions cannot be stored as a marketing claim.")


def _audit_unscoped(actor: str, correlation_id: str, action: str) -> None:
    AuditEvent.objects.create(
        actor_type=AuditEvent.ActorType.AGENT,
        actor_id=actor.strip() or "api",
        action=action,
        object_type="marketing.MarketingClaim",
        object_id="",
        correlation_id=correlation_id.strip(),
        metadata={"external_action": False},
    )


def _audit(action: str, obj, actor: str, correlation_id: str, metadata: dict) -> None:
    AuditEvent.objects.create(
        actor_type=AuditEvent.ActorType.AGENT,
        actor_id=actor,
        action=action,
        object_type=f"marketing.{obj.__class__.__name__}",
        object_id=str(obj.id),
        correlation_id=correlation_id,
        metadata={**metadata, "external_action": False},
    )
