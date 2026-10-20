import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from core.models import IdempotencyRecord
from core.services import canonical_hash
from mailbox.models import MockEmailMessage
from mailbox.services import (
    EmailAlreadyIngestedError,
    InvalidEmailPayloadError,
    MailboxError,
    ingest_mock_email,
    list_email_messages,
    serialize_email_message,
)


def error_response(code: str, message: str, status: int) -> JsonResponse:
    return JsonResponse({"error": {"code": code, "message": message}}, status=status)


def change_headers(request) -> tuple[str, str, str]:
    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    correlation_id = request.headers.get("X-Correlation-ID", "").strip()
    actor_id = request.headers.get("X-Actor-ID", "api").strip() or "api"
    if not idempotency_key or not correlation_id:
        raise InvalidEmailPayloadError("Idempotency-Key and X-Correlation-ID are required.")
    return idempotency_key, correlation_id, actor_id


@login_required
@require_GET
def inbox_dashboard(request):
    classification = request.GET.get("classification", "").strip()
    if classification and classification not in MockEmailMessage.Classification.values:
        classification = ""
    return render(
        request,
        "mailbox/inbox_dashboard.html",
        {
            "messages": list_email_messages(classification=classification),
            "classifications": MockEmailMessage.Classification.values,
            "selected_classification": classification,
        },
    )


@require_GET
def email_list(request):
    classification = request.GET.get("classification", "").strip()
    limit_raw = request.GET.get("limit", "100").strip()
    if classification and classification not in MockEmailMessage.Classification.values:
        return error_response("INVALID_EMAIL_FILTER", "classification must be valid.", 400)
    try:
        limit = int(limit_raw)
    except ValueError:
        return error_response("INVALID_EMAIL_FILTER", "limit must be an integer.", 400)
    if limit < 1 or limit > 200:
        return error_response("INVALID_EMAIL_FILTER", "limit must be between 1 and 200.", 400)
    messages = list_email_messages(classification=classification, limit=limit)
    return JsonResponse({"emails": [serialize_email_message(message) for message in messages]})


@csrf_exempt
@require_POST
def mock_email_ingest(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidEmailPayloadError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        message, created = ingest_mock_email(payload, actor_id=actor_id, correlation_id=correlation_id)
        response = {"email": serialize_email_message(message), "created": created, "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=201 if created else 200)
        return JsonResponse(response, status=201 if created else 200)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except EmailAlreadyIngestedError as exc:
        return error_response(exc.code, str(exc), 409)
    except InvalidEmailPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except MailboxError as exc:
        return error_response(exc.code, str(exc), 400)
