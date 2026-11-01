import json
import uuid

from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.models import IdempotencyRecord
from core.services import canonical_hash
from marketing.models import MarketingArtifact, MarketingRequest
from marketing.services import (
    InvalidMarketingPayloadError,
    MarketingAccessDeniedError,
    MarketingBlockedError,
    MarketingError,
    analyze_performance,
    create_campaign_brief,
    create_marketing_request,
    decision_summary,
    marketing_status,
    review_artifact,
    revise_artifact,
    serialize_artifact,
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


@require_http_methods(["GET", "POST"])
def marketing_dashboard(request):
    error = ""
    if request.method == "POST":
        objective = request.POST.get("objective", "")
        payload = {
            "objective": objective,
            "geography": [item.strip() for item in request.POST.get("geography", "").split(",") if item.strip()],
            "budget_amount": request.POST.get("budget_amount", "").strip() or None,
            "currency": request.POST.get("currency", "").strip(),
            "time_horizon": request.POST.get("time_horizon", "30 days").strip() or "30 days",
        }
        idempotency_key = request.POST.get("idempotency_key", "").strip() or str(uuid.uuid4())
        try:
            create_marketing_request(payload, actor_id="marketing_dashboard", correlation_id=idempotency_key)
            return redirect("marketing-dashboard")
        except (InvalidMarketingPayloadError, MarketingBlockedError, MarketingError) as exc:
            error = str(exc)
    requests = list(MarketingRequest.objects.order_by("-created_at")[:20])
    return render(
        request,
        "marketing/dashboard.html",
        {
            "status": marketing_status(),
            "requests": requests,
            "error": error,
            "idempotency_key": uuid.uuid4(),
        },
    )
