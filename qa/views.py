import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from core.models import IdempotencyRecord
from core.services import canonical_hash, serialize_task_summary
from operations.models import Task
from qa.services import (
    InvalidQaPayloadError,
    QaBlockedError,
    QaError,
    list_verification_queue,
    qa_status,
    review_task_evidence,
    serialize_verification_review,
)


def error_response(code: str, message: str, status: int) -> JsonResponse:
    return JsonResponse({"error": {"code": code, "message": message}}, status=status)


def change_headers(request):
    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    correlation_id = request.headers.get("X-Correlation-ID", "").strip()
    actor_id = request.headers.get("X-Actor-ID", "qa_agent").strip() or "qa_agent"
    if not idempotency_key or not correlation_id:
        raise InvalidQaPayloadError("Idempotency-Key and X-Correlation-ID are required.")
    return idempotency_key, correlation_id, actor_id


@require_GET
def qa_status_view(request):
    return JsonResponse({"status": qa_status()})


@require_GET
def qa_verification_queue(request):
    return JsonResponse({"tasks": [serialize_task_summary(task) for task in list_verification_queue()]})


@csrf_exempt
@require_POST
def qa_task_review(request, task_id):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidQaPayloadError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        review = review_task_evidence(payload, task_id=str(task_id), actor_id=actor_id, correlation_id=correlation_id)
        review.task.refresh_from_db()
        response = {
            "verification_review": serialize_verification_review(review),
            "task": serialize_task_summary(review.task),
            "correlation_id": correlation_id,
        }
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=200)
        return JsonResponse(response, status=200)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except Task.DoesNotExist:
        return error_response("TASK_NOT_FOUND", "Task was not found.", 404)
    except InvalidQaPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except QaBlockedError as exc:
        return error_response(exc.code, str(exc), 409)
    except QaError as exc:
        return error_response(exc.code, str(exc), 400)

