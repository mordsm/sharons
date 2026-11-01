import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from core.models import IdempotencyRecord
from core.services import canonical_hash
from governance.models import SecretReference
from governance.secrets import (
    InvalidSecretReferenceError,
    SecretReferenceError,
    create_secret_reference,
    serialize_secret_reference,
)


def error_response(code: str, message: str, status: int) -> JsonResponse:
    return JsonResponse({"error": {"code": code, "message": message}}, status=status)


@csrf_exempt
@require_POST
def secret_reference_create(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidSecretReferenceError("Request body must be a JSON object.")
        idempotency_key = request.headers.get("Idempotency-Key", "").strip()
        correlation_id = request.headers.get("X-Correlation-ID", "").strip()
        actor_id = request.headers.get("X-Actor-ID", "api").strip() or "api"
        if not idempotency_key or not correlation_id:
            raise InvalidSecretReferenceError("Idempotency-Key and X-Correlation-ID are required.")
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)
        reference = create_secret_reference(payload, actor_id=actor_id, correlation_id=correlation_id)
        response = {"secret_reference": serialize_secret_reference(reference), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=201)
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except InvalidSecretReferenceError as exc:
        return error_response(exc.code, str(exc), 400)
    except SecretReferenceError as exc:
        return error_response(exc.code, str(exc), 400)


@require_GET
def secret_reference_list(request):
    references = SecretReference.objects.all()
    return JsonResponse({
        "secret_references": [serialize_secret_reference(reference) for reference in references],
        "stores_secret_value": False,
    })
