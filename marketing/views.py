import json
import uuid

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.models import IdempotencyRecord
from core.services import canonical_hash
from marketing.models import ContentCalendarItem, MarketingArtifact, MarketingClaim, MarketingExperiment, MarketingRequest
from marketing.services import (
    InvalidMarketingPayloadError,
    MarketingAccessDeniedError,
    MarketingBlockedError,
    MarketingError,
    analyze_performance,
    create_calendar_item,
    create_campaign_brief,
    create_claim,
    create_experiment,
    create_marketing_request,
    decision_summary,
    marketing_status,
    review_artifact,
    review_calendar_item,
    review_claim,
    review_experiment,
    revise_artifact,
    serialize_artifact,
    serialize_calendar_item,
    serialize_claim,
    serialize_experiment,
    serialize_request,
)
from portfolio.models import Objective, Project


def error_response(code: str, message: str, status: int) -> JsonResponse:
    return JsonResponse({"error": {"code": code, "message": message}}, status=status)


def change_headers(request):
    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    correlation_id = request.headers.get("X-Correlation-ID", "").strip()
    actor_id = request.headers.get("X-Actor-ID", "api").strip() or "api"
    if not idempotency_key or not correlation_id:
        raise InvalidMarketingPayloadError("Idempotency-Key and X-Correlation-ID are required.")
    return idempotency_key, correlation_id, actor_id


def idempotent_context(request, payload: dict):
    idempotency_key, correlation_id, actor_id = change_headers(request)
    request_hash = canonical_hash({"path": request.path, "payload": payload})
    existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
    if existing:
        if existing.request_hash != request_hash:
            return None, error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
        return None, JsonResponse(existing.response_payload, status=existing.status_code)
    return (idempotency_key, correlation_id, actor_id, request_hash), None


def _json_payload(request) -> dict:
    payload = json.loads(request.body.decode("utf-8") or "{}")
    if not isinstance(payload, dict):
        raise InvalidMarketingPayloadError("Request body must be a JSON object.")
    return payload


@require_GET
def marketing_status_view(request):
    return JsonResponse({"status": marketing_status()})


@csrf_exempt
@require_POST
def marketing_request_create(request):
    try:
        payload = _json_payload(request)
        context, existing = idempotent_context(request, payload)
        if existing:
            return existing
        idempotency_key, correlation_id, actor_id, request_hash = context
        marketing_request = create_marketing_request(payload, actor_id=actor_id, correlation_id=correlation_id)
        response = {"marketing_request": serialize_request(marketing_request), "correlation_id": correlation_id, "external_action": False}
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=201)
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except (Project.DoesNotExist, Objective.DoesNotExist):
        return error_response("PROJECT_NOT_FOUND", "Project was not found.", 404)
    except InvalidMarketingPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except MarketingAccessDeniedError as exc:
        return error_response(exc.code, str(exc), 403)
    except MarketingBlockedError as exc:
        return error_response(exc.code, str(exc), 409)
    except MarketingError as exc:
        return error_response(exc.code, str(exc), 400)


@require_GET
def marketing_request_detail(request, request_id):
    try:
        marketing_request = MarketingRequest.objects.get(id=request_id)
    except MarketingRequest.DoesNotExist:
        return error_response("MARKETING_REQUEST_NOT_FOUND", "Marketing request was not found.", 404)
    return JsonResponse({"marketing_request": serialize_request(marketing_request), "decision_summary": decision_summary(str(marketing_request.id))})


@csrf_exempt
@require_POST
def marketing_campaign_brief_create(request, request_id):
    try:
        payload = _json_payload(request)
        context, existing = idempotent_context(request, payload)
        if existing:
            return existing
        idempotency_key, correlation_id, actor_id, request_hash = context
        artifact = create_campaign_brief(payload, request_id=str(request_id), actor_id=actor_id, correlation_id=correlation_id)
        response = {"artifact": serialize_artifact(artifact), "correlation_id": correlation_id, "external_action": False}
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=201)
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except MarketingRequest.DoesNotExist:
        return error_response("MARKETING_REQUEST_NOT_FOUND", "Marketing request was not found.", 404)
    except InvalidMarketingPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except MarketingBlockedError as exc:
        return error_response(exc.code, str(exc), 409)


@csrf_exempt
@require_POST
def marketing_artifact_review(request, artifact_id):
    try:
        payload = _json_payload(request)
        context, existing = idempotent_context(request, payload)
        if existing:
            return existing
        idempotency_key, correlation_id, actor_id, request_hash = context
        artifact = review_artifact(payload, artifact_id=str(artifact_id), actor_id=actor_id, correlation_id=correlation_id)
        response = {"artifact": serialize_artifact(artifact), "correlation_id": correlation_id, "external_action": False}
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=200)
        return JsonResponse(response, status=200)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except MarketingArtifact.DoesNotExist:
        return error_response("MARKETING_ARTIFACT_NOT_FOUND", "Marketing artifact was not found.", 404)
    except InvalidMarketingPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except MarketingBlockedError as exc:
        return error_response(exc.code, str(exc), 409)


@csrf_exempt
@require_POST
def marketing_artifact_revise(request, artifact_id):
    try:
        payload = _json_payload(request)
        context, existing = idempotent_context(request, payload)
        if existing:
            return existing
        idempotency_key, correlation_id, actor_id, request_hash = context
        artifact = revise_artifact(payload, artifact_id=str(artifact_id), actor_id=actor_id, correlation_id=correlation_id)
        response = {"artifact": serialize_artifact(artifact), "correlation_id": correlation_id, "external_action": False}
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=201)
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except MarketingArtifact.DoesNotExist:
        return error_response("MARKETING_ARTIFACT_NOT_FOUND", "Marketing artifact was not found.", 404)
    except InvalidMarketingPayloadError as exc:
        return error_response(exc.code, str(exc), 400)


@csrf_exempt
@require_POST
def marketing_performance_analyze(request):
    try:
        payload = _json_payload(request)
        context, existing = idempotent_context(request, payload)
        if existing:
            return existing
        idempotency_key, correlation_id, actor_id, request_hash = context
        marketing_request = analyze_performance(payload, actor_id=actor_id, correlation_id=correlation_id)
        response = {"marketing_request": serialize_request(marketing_request), "correlation_id": correlation_id, "external_action": False}
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=201)
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except InvalidMarketingPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except MarketingAccessDeniedError as exc:
        return error_response(exc.code, str(exc), 403)
    except MarketingBlockedError as exc:
        return error_response(exc.code, str(exc), 409)


def _record_mutation(request, payload, handler, success_status, missing):
    try:
        context, existing = idempotent_context(request, payload)
        if existing:
            return existing
        idempotency_key, correlation_id, actor_id, request_hash = context
        result = handler(payload, actor_id=actor_id, correlation_id=correlation_id)
        response = {**result, "correlation_id": correlation_id, "external_action": False}
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=success_status)
        return JsonResponse(response, status=success_status)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except missing as exc:
        return error_response("MARKETING_REQUEST_NOT_FOUND", str(exc) or "Marketing record was not found.", 404)
    except InvalidMarketingPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except MarketingAccessDeniedError as exc:
        return error_response(exc.code, str(exc), 403)
    except MarketingBlockedError as exc:
        return error_response(exc.code, str(exc), 409)


@csrf_exempt
@require_POST
def marketing_calendar_create(request, request_id):
    try:
        payload = _json_payload(request)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except InvalidMarketingPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    return _record_mutation(
        request,
        payload,
        lambda payload, actor_id, correlation_id: {
            "calendar_item": serialize_calendar_item(
                create_calendar_item(payload, request_id=str(request_id), actor_id=actor_id, correlation_id=correlation_id)
            )
        },
        201,
        (MarketingRequest.DoesNotExist,),
    )


@csrf_exempt
@require_POST
def marketing_calendar_review(request, item_id):
    try:
        payload = _json_payload(request)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except InvalidMarketingPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    return _record_mutation(
        request,
        payload,
        lambda payload, actor_id, correlation_id: {
            "calendar_item": serialize_calendar_item(
                review_calendar_item(payload, item_id=str(item_id), actor_id=actor_id, correlation_id=correlation_id)
            )
        },
        200,
        (ContentCalendarItem.DoesNotExist,),
    )


@csrf_exempt
@require_POST
def marketing_experiment_create(request, request_id):
    try:
        payload = _json_payload(request)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except InvalidMarketingPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    return _record_mutation(
        request,
        payload,
        lambda payload, actor_id, correlation_id: {
            "experiment": serialize_experiment(
                create_experiment(payload, request_id=str(request_id), actor_id=actor_id, correlation_id=correlation_id)
            )
        },
        201,
        (MarketingRequest.DoesNotExist,),
    )


@csrf_exempt
@require_POST
def marketing_experiment_review(request, experiment_id):
    try:
        payload = _json_payload(request)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except InvalidMarketingPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    return _record_mutation(
        request,
        payload,
        lambda payload, actor_id, correlation_id: {
            "experiment": serialize_experiment(
                review_experiment(payload, experiment_id=str(experiment_id), actor_id=actor_id, correlation_id=correlation_id)
            )
        },
        200,
        (MarketingExperiment.DoesNotExist,),
    )


@csrf_exempt
@require_POST
def marketing_claim_create(request, request_id):
    try:
        payload = _json_payload(request)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except InvalidMarketingPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    return _record_mutation(
        request,
        payload,
        lambda payload, actor_id, correlation_id: {
            "claim": serialize_claim(create_claim(payload, request_id=str(request_id), actor_id=actor_id, correlation_id=correlation_id))
        },
        201,
        (MarketingRequest.DoesNotExist,),
    )


@csrf_exempt
@require_POST
def marketing_claim_review(request, claim_id):
    try:
        payload = _json_payload(request)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except InvalidMarketingPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    return _record_mutation(
        request,
        payload,
        lambda payload, actor_id, correlation_id: {
            "claim": serialize_claim(review_claim(payload, claim_id=str(claim_id), actor_id=actor_id, correlation_id=correlation_id))
        },
        200,
        (MarketingClaim.DoesNotExist,),
    )


@require_http_methods(["GET", "POST"])
def marketing_dashboard(request):
    error = ""
    if request.method == "POST":
        action = request.POST.get("action", "plan").strip() or "plan"
        correlation_id = request.POST.get("idempotency_key", "").strip() or str(uuid.uuid4())
        try:
            if action == "plan":
                payload = {
                    "objective": request.POST.get("objective", ""),
                    "geography": [item.strip() for item in request.POST.get("geography", "").split(",") if item.strip()],
                    "budget_amount": request.POST.get("budget_amount", "").strip() or None,
                    "currency": request.POST.get("currency", "").strip(),
                    "time_horizon": request.POST.get("time_horizon", "30 days").strip() or "30 days",
                }
                create_marketing_request(payload, actor_id="marketing_dashboard", correlation_id=correlation_id)
            elif action == "calendar":
                create_calendar_item(
                    {
                        "title": request.POST.get("title", ""),
                        "channel": request.POST.get("channel", ""),
                        "planned_on": request.POST.get("planned_on", ""),
                        "body": request.POST.get("body", ""),
                    },
                    request_id=request.POST.get("request_id", ""),
                    actor_id="marketing_dashboard",
                    correlation_id=correlation_id,
                )
            elif action == "experiment":
                create_experiment(
                    {
                        "hypothesis": request.POST.get("hypothesis", ""),
                        "metric": request.POST.get("metric", ""),
                        "notes": request.POST.get("notes", ""),
                        "sample_size": request.POST.get("sample_size", ""),
                    },
                    request_id=request.POST.get("request_id", ""),
                    actor_id="marketing_dashboard",
                    correlation_id=correlation_id,
                )
            elif action == "claim":
                create_claim(
                    {"text": request.POST.get("text", ""), "evidence_note": request.POST.get("evidence_note", ""), "supported": False},
                    request_id=request.POST.get("request_id", ""),
                    actor_id="marketing_dashboard",
                    correlation_id=correlation_id,
                )
            elif action == "review_calendar":
                review_calendar_item(
                    {"decision": request.POST.get("decision", "")},
                    item_id=request.POST.get("item_id", ""),
                    actor_id="marketing_dashboard",
                    correlation_id=correlation_id,
                )
            elif action == "review_experiment":
                review_experiment(
                    {"decision": request.POST.get("decision", "")},
                    experiment_id=request.POST.get("item_id", ""),
                    actor_id="marketing_dashboard",
                    correlation_id=correlation_id,
                )
            elif action == "review_claim":
                review_claim(
                    {
                        "decision": request.POST.get("decision", ""),
                        "evidence_note": request.POST.get("evidence_note", ""),
                        "acknowledge_unsupported": request.POST.get("acknowledge_unsupported") == "yes",
                    },
                    claim_id=request.POST.get("item_id", ""),
                    actor_id="marketing_dashboard",
                    correlation_id=correlation_id,
                )
            else:
                raise InvalidMarketingPayloadError("Unknown dashboard action.")
            return redirect("marketing-dashboard")
        except (MarketingRequest.DoesNotExist, ContentCalendarItem.DoesNotExist, MarketingExperiment.DoesNotExist, MarketingClaim.DoesNotExist, ValidationError):
            error = "That marketing record was not found."
        except (InvalidMarketingPayloadError, MarketingBlockedError, MarketingError) as exc:
            error = str(exc)
    requests = list(MarketingRequest.objects.order_by("-created_at")[:20])
    return render(
        request,
        "marketing/dashboard.html",
        {
            "status": marketing_status(),
            "requests": requests,
            "calendar_items": list(ContentCalendarItem.objects.select_related("request").order_by("planned_on")[:20]),
            "experiments": list(MarketingExperiment.objects.select_related("request").order_by("-created_at")[:20]),
            "claims": list(MarketingClaim.objects.select_related("request").order_by("created_at")[:20]),
            "error": error,
            "idempotency_key": uuid.uuid4(),
        },
    )
