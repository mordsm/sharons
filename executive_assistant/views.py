import json
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from core.models import IdempotencyRecord
from core.services import canonical_hash
from operations.models import Task
from executive_assistant.forms import (
    ExecutiveBriefArchiveForm,
    ExecutiveBriefCreateForm,
    ExecutiveBriefTaskProposalForm,
    ExecutiveEmailDraftApprovalRequestForm,
    ExecutiveEmailDraftReviewForm,
    ExecutiveReadOnlyCalendarIngestForm,
    ExecutiveReadOnlyEmailIngestForm,
    ExecutiveProviderSyncConfigForm,
    ExecutiveTaskProposalReviewForm,
)
from executive_assistant.models import (
    ExecutiveBrief,
    ExecutiveBriefTaskProposal,
    ExecutiveCalendarEvent,
    ExecutiveEmailDraft,
    ExecutiveProviderSyncConfig,
    DelegatedTaskFollowUp,
)
from executive_assistant.ea_engine import (
    CalendarConflictEngine,
    EmailTriageAndDraftEngine,
    MorningExecutiveBriefEngine,
    DelegationTrackerEngine,
)
from governance.models import RuleEngineWorkItem
from governance.services import serialize_approval_request
from governance.services import InvalidRuleEngineWorkItemUpdateError, list_rule_engine_work_items, update_rule_engine_work_item
from mailbox.models import MockEmailMessage
from mailbox.services import serialize_email_message
from executive_assistant.services import (
    ExecutiveAssistantError,
    ExecutiveBriefBlockedError,
    ExecutiveProviderConnectorBlockedError,
    InvalidExecutiveBriefPayloadError,
    archive_executive_brief,
    create_provider_sync_config,
    create_email_draft_from_message,
    create_email_draft_approval_request,
    create_executive_brief,
    dry_run_provider_sync_config,
    executive_assistant_operational_snapshot,
    executive_assistant_status,
    executive_assistant_queue_counts,
    ingest_read_only_email,
    ingest_read_only_calendar_event,
    list_calendar_events,
    list_email_drafts,
    list_provider_sync_configs,
    propose_tasks_from_brief,
    provider_connector_status,
    provider_readiness_summary,
    provider_sync_config_plan,
    provider_sync_config_readiness,
    review_email_draft,
    review_task_proposal,
    serialize_email_draft,
    serialize_calendar_event,
    serialize_executive_brief,
    serialize_provider_sync_config,
    serialize_task_proposal,
)


def error_response(code: str, message: str, status: int) -> JsonResponse:
    return JsonResponse({"error": {"code": code, "message": message}}, status=status)


def change_headers(request):
    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    correlation_id = request.headers.get("X-Correlation-ID", "").strip()
    actor_id = request.headers.get("X-Actor-ID", "api").strip() or "api"
    if not idempotency_key or not correlation_id:
        raise InvalidExecutiveBriefPayloadError("Idempotency-Key and X-Correlation-ID are required.")
    return idempotency_key, correlation_id, actor_id


def dashboard_actor_id(request) -> str:
    if request.user.is_authenticated:
        return str(request.user.get_username())
    return "executive_assistant_dashboard"


def dashboard_correlation_id(action: str) -> str:
    return f"dashboard-executive-assistant-{action}"


def dashboard_idempotency_conflict(*, key: str, payload: dict) -> bool:
    request_hash = canonical_hash(payload)
    existing = IdempotencyRecord.objects.filter(key=key).first()
    return bool(existing and existing.request_hash != request_hash)


def dashboard_idempotency_seen(*, key: str, payload: dict) -> bool:
    request_hash = canonical_hash(payload)
    existing = IdempotencyRecord.objects.filter(key=key).first()
    return bool(existing and existing.request_hash == request_hash)


def record_dashboard_idempotency(*, key: str, payload: dict, response_payload: dict) -> None:
    IdempotencyRecord.objects.create(
        key=key,
        request_hash=canonical_hash(payload),
        response_payload=response_payload,
        status_code=303,
    )


@login_required
@require_http_methods(["GET", "POST"])
def executive_assistant_dashboard(request):
    if request.method == "POST":
        action = request.POST.get("action", "").strip()
        actor_id = dashboard_actor_id(request)
        correlation_id = dashboard_correlation_id(action)
        try:
            if action == "create_brief":
                form = ExecutiveBriefCreateForm(request.POST)
                if not form.is_valid():
                    raise ValueError("Brief form is invalid.")
                source_window = {}
                if form.cleaned_data["source_window_days"]:
                    source_window["days"] = form.cleaned_data["source_window_days"]
                payload = {
                    "action": action,
                    "brief_type": form.cleaned_data["brief_type"],
                    "title": form.cleaned_data["title"],
                    "source_window": source_window,
                }
                idempotency_key = form.cleaned_data["idempotency_key"]
                if dashboard_idempotency_conflict(key=idempotency_key, payload=payload):
                    raise ValueError("Idempotency key was already used for a different dashboard action.")
                if not dashboard_idempotency_seen(key=idempotency_key, payload=payload):
                    brief = create_executive_brief(payload, actor_id=actor_id, correlation_id=correlation_id)
                    record_dashboard_idempotency(
                        key=idempotency_key,
                        payload=payload,
                        response_payload={"brief_id": str(brief.id), "status": brief.status},
                    )
                messages.success(request, "Executive brief created.")

            elif action == "ingest_read_only_email":
                form = ExecutiveReadOnlyEmailIngestForm(request.POST)
                if not form.is_valid():
                    raise ValueError("Read-only email ingest form is invalid.")
                payload = {
                    "action": action,
                    "source": form.cleaned_data["source"],
                    "external_event_id": form.cleaned_data["external_event_id"],
                    "sender": form.cleaned_data["sender"],
                    "subject": form.cleaned_data["subject"],
                    "body": form.cleaned_data["body"],
                }
                idempotency_key = form.cleaned_data["idempotency_key"]
                if dashboard_idempotency_conflict(key=idempotency_key, payload=payload):
                    raise ValueError("Idempotency key was already used for a different dashboard action.")
                if not dashboard_idempotency_seen(key=idempotency_key, payload=payload):
                    message, created = ingest_read_only_email(payload, actor_id=actor_id, correlation_id=correlation_id)
                    record_dashboard_idempotency(
                        key=idempotency_key,
                        payload=payload,
                        response_payload={"message_id": str(message.id), "created": created, "classification": message.classification},
                    )
                messages.success(request, "Read-only email ingested.")

            elif action == "ingest_read_only_calendar_event":
                form = ExecutiveReadOnlyCalendarIngestForm(request.POST)
                if not form.is_valid():
                    raise ValueError("Read-only calendar ingest form is invalid.")
                attendees = [
                    item.strip()
                    for item in str(form.cleaned_data["attendees"]).split(",")
                    if item.strip()
                ]
                payload = {
                    "action": action,
                    "source": form.cleaned_data["source"],
                    "external_event_id": form.cleaned_data["external_event_id"],
                    "title": form.cleaned_data["title"],
                    "starts_at": form.cleaned_data["starts_at"].isoformat(),
                    "ends_at": form.cleaned_data["ends_at"].isoformat(),
                    "organizer": form.cleaned_data["organizer"],
                    "attendees": attendees,
                    "location": form.cleaned_data["location"],
                    "description": form.cleaned_data["description"],
                }
                idempotency_key = form.cleaned_data["idempotency_key"]
                if dashboard_idempotency_conflict(key=idempotency_key, payload=payload):
                    raise ValueError("Idempotency key was already used for a different dashboard action.")
                if not dashboard_idempotency_seen(key=idempotency_key, payload=payload):
                    event, created = ingest_read_only_calendar_event(payload, actor_id=actor_id, correlation_id=correlation_id)
                    record_dashboard_idempotency(
                        key=idempotency_key,
                        payload=payload,
                        response_payload={"event_id": str(event.id), "created": created, "status": event.status},
                    )
                messages.success(request, "Read-only calendar event ingested.")

            elif action == "upsert_provider_sync_config":
                form = ExecutiveProviderSyncConfigForm(request.POST)
                if not form.is_valid():
                    raise ValueError("Provider sync config form is invalid.")
                scopes = [
                    item.strip()
                    for item in str(form.cleaned_data["scopes"]).split(",")
                    if item.strip()
                ]
                payload = {
                    "action": action,
                    "provider_type": form.cleaned_data["provider_type"],
                    "provider_name": form.cleaned_data["provider_name"],
                    "source": form.cleaned_data["source"],
                    "status": form.cleaned_data["status"],
                    "sync_mode": ExecutiveProviderSyncConfig.SyncMode.READ_ONLY,
                    "scopes": scopes,
                    "config": {},
                }
                idempotency_key = form.cleaned_data["idempotency_key"]
                if dashboard_idempotency_conflict(key=idempotency_key, payload=payload):
                    raise ValueError("Idempotency key was already used for a different dashboard action.")
                if not dashboard_idempotency_seen(key=idempotency_key, payload=payload):
                    sync_config, created = create_provider_sync_config(payload, actor_id=actor_id, correlation_id=correlation_id)
                    record_dashboard_idempotency(
                        key=idempotency_key,
                        payload=payload,
                        response_payload={"provider_sync_config_id": str(sync_config.id), "created": created, "status": sync_config.status},
                    )
                messages.success(request, "Provider sync config saved.")

            elif action == "propose_tasks":
                form = ExecutiveBriefTaskProposalForm(request.POST)
                if not form.is_valid():
                    raise ValueError("Task proposal form is invalid.")
                brief_id = str(request.POST.get("brief_id", "")).strip()
                payload = {
                    "action": action,
                    "brief_id": brief_id,
                    "objective_id": str(form.cleaned_data["objective_id"].id),
                }
                idempotency_key = form.cleaned_data["idempotency_key"]
                if dashboard_idempotency_conflict(key=idempotency_key, payload=payload):
                    raise ValueError("Idempotency key was already used for a different dashboard action.")
                if not dashboard_idempotency_seen(key=idempotency_key, payload=payload):
                    proposals = propose_tasks_from_brief(payload, brief_id=brief_id, actor_id=actor_id, correlation_id=correlation_id)
                    record_dashboard_idempotency(
                        key=idempotency_key,
                        payload=payload,
                        response_payload={"brief_id": brief_id, "task_proposals": [str(proposal.id) for proposal in proposals]},
                    )
                messages.success(request, "Task proposals created.")

            elif action == "archive_brief":
                form = ExecutiveBriefArchiveForm(request.POST)
                if not form.is_valid():
                    raise ValueError("Archive form is invalid.")
                brief_id = str(request.POST.get("brief_id", "")).strip()
                payload = {
                    "action": action,
                    "brief_id": brief_id,
                }
                idempotency_key = form.cleaned_data["idempotency_key"]
                if dashboard_idempotency_conflict(key=idempotency_key, payload=payload):
                    raise ValueError("Idempotency key was already used for a different dashboard action.")
                if not dashboard_idempotency_seen(key=idempotency_key, payload=payload):
                    brief = archive_executive_brief(brief_id=brief_id, actor_id=actor_id, correlation_id=correlation_id)
                    record_dashboard_idempotency(
                        key=idempotency_key,
                        payload=payload,
                        response_payload={"brief_id": str(brief.id), "status": brief.status},
                    )
                messages.success(request, "Executive brief archived.")

            elif action == "review_proposal":
                form = ExecutiveTaskProposalReviewForm(request.POST)
                if not form.is_valid():
                    raise ValueError("Proposal review form is invalid.")
                proposal_id = str(request.POST.get("proposal_id", "")).strip()
                payload = {
                    "action": action,
                    "proposal_id": proposal_id,
                    "decision": form.cleaned_data["decision"],
                    "review_note": form.cleaned_data["review_note"],
                }
                idempotency_key = form.cleaned_data["idempotency_key"]
                if dashboard_idempotency_conflict(key=idempotency_key, payload=payload):
                    raise ValueError("Idempotency key was already used for a different dashboard action.")
                if not dashboard_idempotency_seen(key=idempotency_key, payload=payload):
                    proposal = review_task_proposal(payload, proposal_id=proposal_id, actor_id=actor_id, correlation_id=correlation_id)
                    record_dashboard_idempotency(
                        key=idempotency_key,
                        payload=payload,
                        response_payload={"proposal_id": str(proposal.id), "review_status": proposal.review_status},
                    )
                messages.success(request, "Task proposal reviewed.")

            elif action == "review_email_draft":
                form = ExecutiveEmailDraftReviewForm(request.POST)
                if not form.is_valid():
                    raise ValueError("Email draft review form is invalid.")
                draft_id = str(request.POST.get("draft_id", "")).strip()
                payload = {
                    "action": action,
                    "draft_id": draft_id,
                    "decision": form.cleaned_data["decision"],
                    "review_note": form.cleaned_data["review_note"],
                }
                idempotency_key = form.cleaned_data["idempotency_key"]
                if dashboard_idempotency_conflict(key=idempotency_key, payload=payload):
                    raise ValueError("Idempotency key was already used for a different dashboard action.")
                if not dashboard_idempotency_seen(key=idempotency_key, payload=payload):
                    draft = review_email_draft(payload, draft_id=draft_id, actor_id=actor_id, correlation_id=correlation_id)
                    record_dashboard_idempotency(
                        key=idempotency_key,
                        payload=payload,
                        response_payload={"draft_id": str(draft.id), "review_status": draft.review_status},
                    )
                messages.success(request, "Email draft reviewed.")

            elif action == "request_email_draft_approval":
                form = ExecutiveEmailDraftApprovalRequestForm(request.POST)
                if not form.is_valid():
                    raise ValueError("Email draft approval form is invalid.")
                draft_id = str(request.POST.get("draft_id", "")).strip()
                payload = {
                    "action": action,
                    "draft_id": draft_id,
                    "expires_in_hours": form.cleaned_data["expires_in_hours"],
                }
                idempotency_key = form.cleaned_data["idempotency_key"]
                if dashboard_idempotency_conflict(key=idempotency_key, payload=payload):
                    raise ValueError("Idempotency key was already used for a different dashboard action.")
                if not dashboard_idempotency_seen(key=idempotency_key, payload=payload):
                    approval = create_email_draft_approval_request(payload, draft_id=draft_id, actor_id=actor_id, correlation_id=correlation_id)
                    record_dashboard_idempotency(
                        key=idempotency_key,
                        payload=payload,
                        response_payload={"draft_id": draft_id, "approval_id": str(approval.id), "approval_status": approval.status},
                    )
                messages.success(request, "Email draft approval requested.")

            elif action == "complete_rule_engine_work_item":
                item_id = str(request.POST.get("item_id", "")).strip()
                item = RuleEngineWorkItem.objects.get(id=item_id, owner_agent_id="executive_assistant")
                update_rule_engine_work_item(
                    str(item.id),
                    status=RuleEngineWorkItem.Status.COMPLETED,
                    actor_id=actor_id,
                    correlation_id=correlation_id,
                )
                messages.success(request, "Rule-engine work item completed.")

            else:
                raise ValueError("Unknown Executive Assistant action.")
        except (RuleEngineWorkItem.DoesNotExist, InvalidRuleEngineWorkItemUpdateError, Exception) as exc:
            messages.error(request, str(exc))
        return redirect("executive-assistant-dashboard")

    brief_type = request.GET.get("brief_type", "").strip()
    brief_status = request.GET.get("brief_status", "").strip()
    review_status = request.GET.get("review_status", "").strip()

    if brief_type and brief_type not in ExecutiveBrief.BriefType.values:
        brief_type = ""
    if brief_status and brief_status not in ExecutiveBrief.Status.values:
        brief_status = ""
    if review_status and review_status not in ExecutiveBriefTaskProposal.ReviewStatus.values:
        review_status = ""

    briefs = ExecutiveBrief.objects.order_by("-created_at")
    if brief_type:
        briefs = briefs.filter(brief_type=brief_type)
    if brief_status:
        briefs = briefs.filter(status=brief_status)

    proposals = ExecutiveBriefTaskProposal.objects.select_related("brief").order_by("-created_at")
    if review_status:
        proposals = proposals.filter(review_status=review_status)

    return render(
        request,
        "executive_assistant/dashboard.html",
        {
            "briefs": briefs[:50],
            "task_proposals": proposals[:50],
            "email_drafts": list_email_drafts(limit=50),
            "calendar_events": list_calendar_events(limit=50),
            "provider_sync_configs": list_provider_sync_configs(limit=50),
            "provider_readiness_summary": provider_readiness_summary(),
            "rule_engine_work_items": list_rule_engine_work_items(owner_agent_id="executive_assistant", limit=50),
            "brief_types": ExecutiveBrief.BriefType.values,
            "brief_statuses": ExecutiveBrief.Status.values,
            "proposal_review_statuses": ExecutiveBriefTaskProposal.ReviewStatus.values,
            "queue_counts": executive_assistant_queue_counts(),
            "selected_brief_type": brief_type,
            "selected_brief_status": brief_status,
            "selected_review_status": review_status,
            "brief_create_form": ExecutiveBriefCreateForm(),
            "read_only_email_ingest_form": ExecutiveReadOnlyEmailIngestForm(),
            "read_only_calendar_ingest_form": ExecutiveReadOnlyCalendarIngestForm(),
            "provider_sync_config_form": ExecutiveProviderSyncConfigForm(),
            "task_proposal_form": ExecutiveBriefTaskProposalForm(),
            "brief_archive_form": ExecutiveBriefArchiveForm(),
            "proposal_review_form": ExecutiveTaskProposalReviewForm(),
            "email_draft_review_form": ExecutiveEmailDraftReviewForm(),
            "email_draft_approval_form": ExecutiveEmailDraftApprovalRequestForm(),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def executive_brief_detail(request, brief_id):
    brief = get_object_or_404(ExecutiveBrief, id=brief_id)
    if request.method == "POST":
        action = request.POST.get("action", "").strip()
        actor_id = dashboard_actor_id(request)
        correlation_id = dashboard_correlation_id(action)
        try:
            if action == "propose_tasks":
                form = ExecutiveBriefTaskProposalForm(request.POST)
                if not form.is_valid():
                    raise ValueError("Task proposal form is invalid.")
                payload = {
                    "action": action,
                    "brief_id": str(brief.id),
                    "objective_id": str(form.cleaned_data["objective_id"].id),
                }
                idempotency_key = form.cleaned_data["idempotency_key"]
                if dashboard_idempotency_conflict(key=idempotency_key, payload=payload):
                    raise ValueError("Idempotency key was already used for a different dashboard action.")
                if not dashboard_idempotency_seen(key=idempotency_key, payload=payload):
                    proposals = propose_tasks_from_brief(payload, brief_id=str(brief.id), actor_id=actor_id, correlation_id=correlation_id)
                    record_dashboard_idempotency(
                        key=idempotency_key,
                        payload=payload,
                        response_payload={"brief_id": str(brief.id), "task_proposals": [str(proposal.id) for proposal in proposals]},
                    )
                messages.success(request, "Task proposals created.")

            elif action == "archive_brief":
                form = ExecutiveBriefArchiveForm(request.POST)
                if not form.is_valid():
                    raise ValueError("Archive form is invalid.")
                payload = {
                    "action": action,
                    "brief_id": str(brief.id),
                }
                idempotency_key = form.cleaned_data["idempotency_key"]
                if dashboard_idempotency_conflict(key=idempotency_key, payload=payload):
                    raise ValueError("Idempotency key was already used for a different dashboard action.")
                if not dashboard_idempotency_seen(key=idempotency_key, payload=payload):
                    archived = archive_executive_brief(brief_id=str(brief.id), actor_id=actor_id, correlation_id=correlation_id)
                    record_dashboard_idempotency(
                        key=idempotency_key,
                        payload=payload,
                        response_payload={"brief_id": str(archived.id), "status": archived.status},
                    )
                messages.success(request, "Executive brief archived.")

            elif action == "review_proposal":
                form = ExecutiveTaskProposalReviewForm(request.POST)
                if not form.is_valid():
                    raise ValueError("Proposal review form is invalid.")
                proposal_id = str(request.POST.get("proposal_id", "")).strip()
                if not ExecutiveBriefTaskProposal.objects.filter(id=proposal_id, brief=brief).exists():
                    raise ValueError("Task proposal does not belong to this brief.")
                payload = {
                    "action": action,
                    "brief_id": str(brief.id),
                    "proposal_id": proposal_id,
                    "decision": form.cleaned_data["decision"],
                    "review_note": form.cleaned_data["review_note"],
                }
                idempotency_key = form.cleaned_data["idempotency_key"]
                if dashboard_idempotency_conflict(key=idempotency_key, payload=payload):
                    raise ValueError("Idempotency key was already used for a different dashboard action.")
                if not dashboard_idempotency_seen(key=idempotency_key, payload=payload):
                    proposal = review_task_proposal(payload, proposal_id=proposal_id, actor_id=actor_id, correlation_id=correlation_id)
                    record_dashboard_idempotency(
                        key=idempotency_key,
                        payload=payload,
                        response_payload={"proposal_id": str(proposal.id), "review_status": proposal.review_status},
                    )
                messages.success(request, "Task proposal reviewed.")

            else:
                raise ValueError("Unknown Executive Assistant action.")
        except Exception as exc:
            messages.error(request, str(exc))
        return redirect("executive-brief-detail", brief_id=brief.id)

    task_proposals = ExecutiveBriefTaskProposal.objects.filter(brief=brief).order_by("follow_up_index", "created_at")
    return render(
        request,
        "executive_assistant/brief_detail.html",
        {
            "brief": brief,
            "task_proposals": task_proposals,
            "brief_archive_form": ExecutiveBriefArchiveForm(),
            "task_proposal_form": ExecutiveBriefTaskProposalForm(),
            "proposal_review_form": ExecutiveTaskProposalReviewForm(),
        },
    )


@csrf_exempt
@require_POST
def executive_brief_create(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidExecutiveBriefPayloadError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        brief = create_executive_brief(payload, actor_id=actor_id, correlation_id=correlation_id)
        response = {"executive_brief": serialize_executive_brief(brief), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(
            key=idempotency_key,
            request_hash=request_hash,
            response_payload=response,
            status_code=201,
        )
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except InvalidExecutiveBriefPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ExecutiveAssistantError as exc:
        return error_response(exc.code, str(exc), 400)


@require_GET
def executive_briefs_list(request):
    brief_type = request.GET.get("brief_type", "").strip()
    status = request.GET.get("status", "").strip()
    limit_raw = request.GET.get("limit", "100").strip()
    if brief_type and brief_type not in ExecutiveBrief.BriefType.values:
        return error_response("INVALID_EXECUTIVE_BRIEF_FILTER", "brief_type must be valid.", 400)
    if status and status not in ExecutiveBrief.Status.values:
        return error_response("INVALID_EXECUTIVE_BRIEF_FILTER", "status must be valid.", 400)
    try:
        limit = int(limit_raw)
    except ValueError:
        return error_response("INVALID_EXECUTIVE_BRIEF_FILTER", "limit must be an integer.", 400)
    if limit < 1 or limit > 200:
        return error_response("INVALID_EXECUTIVE_BRIEF_FILTER", "limit must be between 1 and 200.", 400)

    briefs = ExecutiveBrief.objects.order_by("-created_at")
    if brief_type:
        briefs = briefs.filter(brief_type=brief_type)
    if status:
        briefs = briefs.filter(status=status)
    return JsonResponse({"executive_briefs": [serialize_executive_brief(brief) for brief in briefs[:limit]]})


@require_GET
def executive_brief_api_detail(request, brief_id):
    try:
        brief = ExecutiveBrief.objects.get(id=brief_id)
    except ExecutiveBrief.DoesNotExist:
        return error_response("EXECUTIVE_BRIEF_NOT_FOUND", "Executive brief was not found.", 404)
    proposals = ExecutiveBriefTaskProposal.objects.filter(brief=brief).order_by("follow_up_index", "created_at")
    return JsonResponse(
        {
            "executive_brief": serialize_executive_brief(brief),
            "task_proposals": [serialize_task_proposal(proposal) for proposal in proposals],
        }
    )


@csrf_exempt
@require_POST
def executive_brief_tasks_propose(request, brief_id):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidExecutiveBriefPayloadError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        proposals = propose_tasks_from_brief(payload, brief_id=str(brief_id), actor_id=actor_id, correlation_id=correlation_id)
        response = {"task_proposals": [serialize_task_proposal(proposal) for proposal in proposals], "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(
            key=idempotency_key,
            request_hash=request_hash,
            response_payload=response,
            status_code=201,
        )
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except ExecutiveBrief.DoesNotExist:
        return error_response("EXECUTIVE_BRIEF_NOT_FOUND", "Executive brief was not found.", 404)
    except InvalidExecutiveBriefPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ExecutiveBriefBlockedError as exc:
        return error_response(exc.code, str(exc), 409)
    except ExecutiveAssistantError as exc:
        return error_response(exc.code, str(exc), 400)


@csrf_exempt
@require_POST
def executive_brief_archive(request, brief_id):
    try:
        idempotency_key, correlation_id, actor_id = change_headers(request)
        payload = {"brief_id": str(brief_id), "action": "archive"}
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        brief = archive_executive_brief(brief_id=str(brief_id), actor_id=actor_id, correlation_id=correlation_id)
        response = {"executive_brief": serialize_executive_brief(brief), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(
            key=idempotency_key,
            request_hash=request_hash,
            response_payload=response,
            status_code=200,
        )
        return JsonResponse(response, status=200)
    except ExecutiveBrief.DoesNotExist:
        return error_response("EXECUTIVE_BRIEF_NOT_FOUND", "Executive brief was not found.", 404)
    except InvalidExecutiveBriefPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ExecutiveBriefBlockedError as exc:
        return error_response(exc.code, str(exc), 409)
    except ExecutiveAssistantError as exc:
        return error_response(exc.code, str(exc), 400)


@require_GET
def executive_task_proposals_list(request):
    review_status = request.GET.get("review_status", "").strip()
    brief_id = request.GET.get("brief_id", "").strip()
    limit_raw = request.GET.get("limit", "100").strip()
    if review_status and review_status not in ExecutiveBriefTaskProposal.ReviewStatus.values:
        return error_response("INVALID_EXECUTIVE_TASK_PROPOSAL_FILTER", "review_status must be valid.", 400)
    try:
        limit = int(limit_raw)
    except ValueError:
        return error_response("INVALID_EXECUTIVE_TASK_PROPOSAL_FILTER", "limit must be an integer.", 400)
    if limit < 1 or limit > 200:
        return error_response("INVALID_EXECUTIVE_TASK_PROPOSAL_FILTER", "limit must be between 1 and 200.", 400)

    proposals = ExecutiveBriefTaskProposal.objects.select_related("brief").order_by("-created_at")
    if review_status:
        proposals = proposals.filter(review_status=review_status)
    if brief_id:
        proposals = proposals.filter(brief_id=brief_id)
    return JsonResponse({"task_proposals": [serialize_task_proposal(proposal) for proposal in proposals[:limit]]})


@require_GET
def executive_task_proposal_detail(request, proposal_id):
    try:
        proposal = ExecutiveBriefTaskProposal.objects.select_related("brief").get(id=proposal_id)
    except ExecutiveBriefTaskProposal.DoesNotExist:
        return error_response("EXECUTIVE_TASK_PROPOSAL_NOT_FOUND", "Executive task proposal was not found.", 404)
    return JsonResponse(
        {
            "task_proposal": serialize_task_proposal(proposal),
            "executive_brief": serialize_executive_brief(proposal.brief),
        }
    )


@csrf_exempt
@require_POST
def executive_task_proposal_review(request, proposal_id):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidExecutiveBriefPayloadError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        proposal = review_task_proposal(payload, proposal_id=str(proposal_id), actor_id=actor_id, correlation_id=correlation_id)
        response = {"task_proposal": serialize_task_proposal(proposal), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(
            key=idempotency_key,
            request_hash=request_hash,
            response_payload=response,
            status_code=200,
        )
        return JsonResponse(response, status=200)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except ExecutiveBriefTaskProposal.DoesNotExist:
        return error_response("EXECUTIVE_TASK_PROPOSAL_NOT_FOUND", "Executive task proposal was not found.", 404)
    except InvalidExecutiveBriefPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ExecutiveBriefBlockedError as exc:
        return error_response(exc.code, str(exc), 409)
    except ExecutiveAssistantError as exc:
        return error_response(exc.code, str(exc), 400)


@require_GET
def executive_email_drafts_list(request):
    review_status = request.GET.get("review_status", "").strip()
    limit_raw = request.GET.get("limit", "100").strip()

    if review_status and review_status not in ExecutiveEmailDraft.ReviewStatus.values:
        return error_response("INVALID_EXECUTIVE_EMAIL_DRAFT_FILTER", "review_status must be valid.", 400)
    try:
        limit = int(limit_raw)
    except ValueError:
        return error_response("INVALID_EXECUTIVE_EMAIL_DRAFT_FILTER", "limit must be an integer.", 400)
    if limit < 1 or limit > 200:
        return error_response("INVALID_EXECUTIVE_EMAIL_DRAFT_FILTER", "limit must be between 1 and 200.", 400)
    drafts = list_email_drafts(review_status=review_status, limit=limit)
    return JsonResponse({"email_drafts": [serialize_email_draft(draft) for draft in drafts]})


@csrf_exempt
@require_POST
def executive_email_draft_create(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidExecutiveBriefPayloadError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        draft = create_email_draft_from_message(payload, actor_id=actor_id, correlation_id=correlation_id)
        response = {"email_draft": serialize_email_draft(draft), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(
            key=idempotency_key,
            request_hash=request_hash,
            response_payload=response,
            status_code=201,
        )
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except MockEmailMessage.DoesNotExist:
        return error_response("EMAIL_MESSAGE_NOT_FOUND", "Source email message was not found.", 404)
    except InvalidExecutiveBriefPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ExecutiveAssistantError as exc:
        return error_response(exc.code, str(exc), 400)


@csrf_exempt
@require_POST
def executive_email_draft_review(request, draft_id):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidExecutiveBriefPayloadError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        draft = review_email_draft(payload, draft_id=str(draft_id), actor_id=actor_id, correlation_id=correlation_id)
        response = {"email_draft": serialize_email_draft(draft), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(
            key=idempotency_key,
            request_hash=request_hash,
            response_payload=response,
            status_code=200,
        )
        return JsonResponse(response, status=200)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except ExecutiveEmailDraft.DoesNotExist:
        return error_response("EXECUTIVE_EMAIL_DRAFT_NOT_FOUND", "Executive email draft was not found.", 404)
    except InvalidExecutiveBriefPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ExecutiveBriefBlockedError as exc:
        return error_response(exc.code, str(exc), 409)
    except ExecutiveAssistantError as exc:
        return error_response(exc.code, str(exc), 400)


@csrf_exempt
@require_POST
def executive_email_draft_approval_request(request, draft_id):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        if not isinstance(payload, dict):
            raise InvalidExecutiveBriefPayloadError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        approval = create_email_draft_approval_request(payload, draft_id=str(draft_id), actor_id=actor_id, correlation_id=correlation_id)
        response = {"approval": serialize_approval_request(approval), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(
            key=idempotency_key,
            request_hash=request_hash,
            response_payload=response,
            status_code=201,
        )
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except ExecutiveEmailDraft.DoesNotExist:
        return error_response("EXECUTIVE_EMAIL_DRAFT_NOT_FOUND", "Executive email draft was not found.", 404)
    except InvalidExecutiveBriefPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ExecutiveBriefBlockedError as exc:
        return error_response(exc.code, str(exc), 409)
    except ExecutiveAssistantError as exc:
        return error_response(exc.code, str(exc), 400)


@csrf_exempt
@require_POST
def executive_read_only_email_ingest(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidExecutiveBriefPayloadError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        message, created = ingest_read_only_email(payload, actor_id=actor_id, correlation_id=correlation_id)
        response = {"email": serialize_email_message(message), "created": created, "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=201 if created else 200)
        return JsonResponse(response, status=201 if created else 200)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except InvalidExecutiveBriefPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ExecutiveAssistantError as exc:
        return error_response(exc.code, str(exc), 400)


@csrf_exempt
@require_POST
def executive_read_only_email_batch_ingest(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidExecutiveBriefPayloadError("Request body must be a JSON object.")
        records = payload.get("emails", [])
        if not isinstance(records, list) or not records:
            raise InvalidExecutiveBriefPayloadError("emails must be a non-empty list.")
        if len(records) > 50:
            raise InvalidExecutiveBriefPayloadError("emails cannot contain more than 50 records.")
        idempotency_key, correlation_id, actor_id = change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        results = []
        created_count = 0
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                raise InvalidExecutiveBriefPayloadError(f"emails[{index}] must be an object.")
            message, created = ingest_read_only_email(record, actor_id=actor_id, correlation_id=correlation_id)
            created_count += int(created)
            results.append({"email": serialize_email_message(message), "created": created})
        response = {
            "emails": results,
            "created_count": created_count,
            "existing_count": len(results) - created_count,
            "correlation_id": correlation_id,
        }
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=201)
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except InvalidExecutiveBriefPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ExecutiveAssistantError as exc:
        return error_response(exc.code, str(exc), 400)


@require_GET
def executive_calendar_events_list(request):
    status = request.GET.get("status", "").strip()
    limit_raw = request.GET.get("limit", "100").strip()
    if status and status not in ExecutiveCalendarEvent.Status.values:
        return error_response("INVALID_EXECUTIVE_CALENDAR_FILTER", "status must be valid.", 400)
    try:
        limit = int(limit_raw)
    except ValueError:
        return error_response("INVALID_EXECUTIVE_CALENDAR_FILTER", "limit must be an integer.", 400)
    if limit < 1 or limit > 200:
        return error_response("INVALID_EXECUTIVE_CALENDAR_FILTER", "limit must be between 1 and 200.", 400)
    events = list_calendar_events(status=status, limit=limit)
    return JsonResponse({"calendar_events": [serialize_calendar_event(event) for event in events]})


@csrf_exempt
@require_POST
def executive_read_only_calendar_ingest(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidExecutiveBriefPayloadError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        event, created = ingest_read_only_calendar_event(payload, actor_id=actor_id, correlation_id=correlation_id)
        response = {"calendar_event": serialize_calendar_event(event), "created": created, "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=201 if created else 200)
        return JsonResponse(response, status=201 if created else 200)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except InvalidExecutiveBriefPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ExecutiveAssistantError as exc:
        return error_response(exc.code, str(exc), 400)


@csrf_exempt
@require_POST
def executive_read_only_calendar_batch_ingest(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidExecutiveBriefPayloadError("Request body must be a JSON object.")
        records = payload.get("events", [])
        if not isinstance(records, list) or not records:
            raise InvalidExecutiveBriefPayloadError("events must be a non-empty list.")
        if len(records) > 50:
            raise InvalidExecutiveBriefPayloadError("events cannot contain more than 50 records.")
        idempotency_key, correlation_id, actor_id = change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        results = []
        created_count = 0
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                raise InvalidExecutiveBriefPayloadError(f"events[{index}] must be an object.")
            event, created = ingest_read_only_calendar_event(record, actor_id=actor_id, correlation_id=correlation_id)
            created_count += int(created)
            results.append({"calendar_event": serialize_calendar_event(event), "created": created})
        response = {
            "calendar_events": results,
            "created_count": created_count,
            "existing_count": len(results) - created_count,
            "correlation_id": correlation_id,
        }
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=201)
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except InvalidExecutiveBriefPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ExecutiveAssistantError as exc:
        return error_response(exc.code, str(exc), 400)


@require_GET
def executive_provider_sync_configs_list(request):
    provider_type = request.GET.get("provider_type", "").strip()
    status = request.GET.get("status", "").strip()
    limit_raw = request.GET.get("limit", "100").strip()
    if provider_type and provider_type not in ExecutiveProviderSyncConfig.ProviderType.values:
        return error_response("INVALID_EXECUTIVE_PROVIDER_SYNC_CONFIG_FILTER", "provider_type must be valid.", 400)
    if status and status not in ExecutiveProviderSyncConfig.Status.values:
        return error_response("INVALID_EXECUTIVE_PROVIDER_SYNC_CONFIG_FILTER", "status must be valid.", 400)
    try:
        limit = int(limit_raw)
    except ValueError:
        return error_response("INVALID_EXECUTIVE_PROVIDER_SYNC_CONFIG_FILTER", "limit must be an integer.", 400)
    if limit < 1 or limit > 200:
        return error_response("INVALID_EXECUTIVE_PROVIDER_SYNC_CONFIG_FILTER", "limit must be between 1 and 200.", 400)
    configs = list_provider_sync_configs(provider_type=provider_type, status=status, limit=limit)
    return JsonResponse({"provider_sync_configs": [serialize_provider_sync_config(config) for config in configs]})


@require_GET
def executive_provider_connectors_status(request):
    return JsonResponse({"provider_connectors": provider_connector_status()})


@require_GET
def executive_provider_readiness_summary(request):
    return JsonResponse({"provider_readiness_summary": provider_readiness_summary()})


@csrf_exempt
@require_POST
def executive_provider_sync_config_create(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidExecutiveBriefPayloadError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        sync_config, created = create_provider_sync_config(payload, actor_id=actor_id, correlation_id=correlation_id)
        response = {
            "provider_sync_config": serialize_provider_sync_config(sync_config),
            "created": created,
            "correlation_id": correlation_id,
        }
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=201 if created else 200)
        return JsonResponse(response, status=201 if created else 200)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except InvalidExecutiveBriefPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ExecutiveAssistantError as exc:
        return error_response(exc.code, str(exc), 400)


@require_GET
def executive_provider_sync_config_readiness(request, config_id):
    try:
        sync_config = ExecutiveProviderSyncConfig.objects.get(id=config_id)
    except ExecutiveProviderSyncConfig.DoesNotExist:
        return error_response("EXECUTIVE_PROVIDER_SYNC_CONFIG_NOT_FOUND", "Provider sync config was not found.", 404)
    return JsonResponse({"readiness": provider_sync_config_readiness(sync_config)})


@require_GET
def executive_provider_sync_config_plan(request, config_id):
    try:
        return JsonResponse(provider_sync_config_plan(config_id=str(config_id)))
    except ExecutiveProviderSyncConfig.DoesNotExist:
        return error_response("EXECUTIVE_PROVIDER_SYNC_CONFIG_NOT_FOUND", "Provider sync config was not found.", 404)


@csrf_exempt
@require_POST
def executive_provider_sync_config_dry_run(request, config_id):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        if not isinstance(payload, dict):
            raise InvalidExecutiveBriefPayloadError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        readiness = dry_run_provider_sync_config(config_id=str(config_id), actor_id=actor_id, correlation_id=correlation_id)
        response = {"readiness": readiness, "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=200)
        return JsonResponse(response, status=200)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except ExecutiveProviderSyncConfig.DoesNotExist:
        return error_response("EXECUTIVE_PROVIDER_SYNC_CONFIG_NOT_FOUND", "Provider sync config was not found.", 404)
    except InvalidExecutiveBriefPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ExecutiveProviderConnectorBlockedError as exc:
        return error_response(exc.code, str(exc), 409)
    except ExecutiveAssistantError as exc:
        return error_response(exc.code, str(exc), 400)


def executive_assistant_status_view(request):
    return JsonResponse({"status": executive_assistant_status()})


@require_GET
def executive_assistant_operational_snapshot_view(request):
    return JsonResponse({"operational_snapshot": executive_assistant_operational_snapshot()})


# ==============================================================================
# Advanced EA Operational APIs (Calendar, Triage, Morning Brief, Delegations)
# ==============================================================================

@require_GET
def calendar_conflicts_api(request):
    """
    Scans upcoming events for direct overlaps and buffer violations.
    """
    buffer_min = int(request.GET.get("buffer_minutes", 15))
    conflicts = CalendarConflictEngine.detect_conflicts(min_buffer_minutes=buffer_min)
    return JsonResponse({"conflicts": conflicts, "total_conflicts": len(conflicts)})


@csrf_exempt
@require_POST
def calendar_reschedule_proposal_api(request):
    """
    Computes available alternative slots within working hours to resolve conflict.
    """
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        event_id = payload.get("event_id")
        if not event_id:
            return error_response("INVALID_PAYLOAD", "event_id is required.", 400)
        search_days = int(payload.get("search_days", 5))
        duration = payload.get("slot_duration_minutes")
        if duration:
            duration = int(duration)
        suggestions = CalendarConflictEngine.suggest_reschedule(
            event_id=event_id,
            search_days=search_days,
            slot_duration_minutes=duration,
        )
        return JsonResponse({"reschedule_proposal": suggestions})
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except ExecutiveCalendarEvent.DoesNotExist:
        return error_response("EVENT_NOT_FOUND", "Calendar event not found.", 404)


@require_GET
def email_triage_api(request):
    """
    Returns heuristically triaged incoming emails with urgency and suggested action.
    """
    limit = int(request.GET.get("limit", 50))
    triaged = EmailTriageAndDraftEngine.triage_emails(limit=limit)
    return JsonResponse({"triaged_emails": triaged, "total_count": len(triaged)})


@csrf_exempt
@require_POST
def email_draft_and_request_approval_api(request):
    """
    Generates an executive draft reply and posts an approval request to Governance.
    """
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        message_id = payload.get("message_id")
        if not message_id:
            return error_response("INVALID_PAYLOAD", "message_id is required.", 400)
        request_approval = bool(payload.get("request_approval", True))
        idempotency_key, correlation_id, actor_id = change_headers(request)

        result = EmailTriageAndDraftEngine.generate_draft_response(
            message_id=message_id,
            request_approval=request_approval,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        return JsonResponse({"draft_result": result}, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except MockEmailMessage.DoesNotExist:
        return error_response("MESSAGE_NOT_FOUND", "Email message not found.", 404)
    except InvalidExecutiveBriefPayloadError as exc:
        return error_response(exc.code, str(exc), 400)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def morning_brief_api(request):
    """
    GET: Returns latest morning brief or compiles current snapshot.
    POST: Force generates a fresh morning brief for today or target date.
    """
    actor_id = request.headers.get("X-Actor-ID", "executive_assistant").strip() or "executive_assistant"
    if request.method == "POST":
        payload = json.loads(request.body.decode("utf-8") or "{}") if request.body else {}
        target_date_str = payload.get("target_date")
        target_date = None
        if target_date_str:
            target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        brief_data = MorningExecutiveBriefEngine.generate_morning_brief(target_date=target_date, actor_id=actor_id)
        return JsonResponse(brief_data, status=201)

    # GET
    today = timezone.now().date()
    existing = ExecutiveBrief.objects.filter(
        brief_type=ExecutiveBrief.BriefType.MORNING_BRIEF,
        created_at__date=today,
    ).order_by("-created_at").first()
    if existing:
        return JsonResponse({
            "brief_id": str(existing.id),
            "title": existing.title,
            "target_date": today.isoformat(),
            "summary": existing.summary,
            "agenda_items": existing.agenda_items,
            "decisions_needed": existing.decisions_needed,
            "urgent_inbox": existing.inbox_items,
            "urgent_delegations": existing.follow_ups,
            "created_at": existing.created_at.isoformat(),
        })

    # If none exists for today, generate one on-the-fly
    brief_data = MorningExecutiveBriefEngine.generate_morning_brief(target_date=today, actor_id=actor_id)
    return JsonResponse(brief_data)


@require_GET
def delegations_report_api(request):
    """
    Returns full tracking report on all delegated commitments.
    """
    report = DelegationTrackerEngine.get_delegations_report()
    return JsonResponse(report)


@csrf_exempt
@require_POST
def delegation_create_api(request):
    """
    Creates a new tracked delegated task follow-up.
    """
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        task_id = payload.get("task_id")
        delegated_to = payload.get("delegated_to")
        due_at_str = payload.get("due_at")
        if not task_id or not delegated_to or not due_at_str:
            return error_response("INVALID_PAYLOAD", "task_id, delegated_to, and due_at are required.", 400)
        
        due_at = datetime.fromisoformat(due_at_str)
        if timezone.is_naive(due_at):
            due_at = timezone.make_aware(due_at)

        title = payload.get("title", "")
        notes = payload.get("notes", "")
        delegated_by = payload.get("delegated_by", "ceo")

        delegation = DelegationTrackerEngine.create_delegation(
            task_id=task_id,
            delegated_to=delegated_to,
            due_at=due_at,
            title=title,
            notes=notes,
            delegated_by=delegated_by,
        )
        return JsonResponse({
            "delegation": {
                "id": str(delegation.id),
                "task_id": str(delegation.task_id),
                "title": delegation.title,
                "delegated_to": delegation.delegated_to,
                "due_at": delegation.due_at.isoformat(),
                "status": delegation.status,
            }
        }, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except Task.DoesNotExist:
        return error_response("TASK_NOT_FOUND", "Task not found.", 404)


@csrf_exempt
@require_POST
def delegation_nudge_api(request, delegation_id):
    """
    Executes an automated follow-up nudge on a delegated task.
    """
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}") if request.body else {}
        nudge_note = payload.get("nudge_note", "")
        actor_id = request.headers.get("X-Actor-ID", "executive_assistant").strip() or "executive_assistant"
        correlation_id = request.headers.get("X-Correlation-ID", "").strip()

        result = DelegationTrackerEngine.nudge_delegation(
            delegation_id=delegation_id,
            nudge_note=nudge_note,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        return JsonResponse({"nudge_result": result})
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except DelegatedTaskFollowUp.DoesNotExist:
        return error_response("DELEGATION_NOT_FOUND", "Delegated follow-up not found.", 404)


@login_required
def morning_brief_page_view(request):
    """
    Dedicated CEO Morning Brief interactive dashboard.
    """
    today = timezone.now().date()
    brief_data = MorningExecutiveBriefEngine.generate_morning_brief(target_date=today, actor_id="ceo")
    delegations = DelegationTrackerEngine.get_delegations_report()
    conflicts = CalendarConflictEngine.detect_conflicts()
    return render(
        request,
        "executive_assistant/morning_brief.html",
        {
            "brief": brief_data,
            "delegations": delegations,
            "conflicts": conflicts,
            "today": today,
        },
    )

