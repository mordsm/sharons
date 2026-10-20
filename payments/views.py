import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.models import IdempotencyRecord
from core.services import canonical_hash
from payments.models import MockPaymentCustomer, MockPaymentSubscription
from payments.providers import get_payment_provider
from payments.services import (
    InvalidPaymentPayloadError,
    PaymentConflictError,
    PaymentError,
    PaymentStateError,
    serialize_customer,
    serialize_subscription,
    serialize_transaction,
    serialize_webhook_event,
)


def error_response(code: str, message: str, status: int) -> JsonResponse:
    return JsonResponse({"error": {"code": code, "message": message}}, status=status)


def load_payload(request) -> dict:
    payload = json.loads(request.body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise InvalidPaymentPayloadError("Request body must be a JSON object.")
    return payload


def begin_idempotent_change(request, payload: dict):
    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    correlation_id = request.headers.get("X-Correlation-ID", "").strip()
    actor_id = request.headers.get("X-Actor-ID", "api").strip() or "api"
    if not idempotency_key or not correlation_id:
        raise InvalidPaymentPayloadError("Idempotency-Key and X-Correlation-ID are required.")
    request_hash = canonical_hash({"path": request.path, "payload": payload})
    existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
    if existing:
        if existing.request_hash != request_hash:
            return None, error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
        return None, JsonResponse(existing.response_payload, status=existing.status_code)
    return (idempotency_key, correlation_id, actor_id, request_hash), None


def persist_idempotent_response(context, response: dict, status_code: int) -> JsonResponse:
    idempotency_key, _correlation_id, _actor_id, request_hash = context
    IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=status_code)
    return JsonResponse(response, status=status_code)


@csrf_exempt
@require_POST
def mock_customer_create(request):
    try:
        payload = load_payload(request)
        context, existing = begin_idempotent_change(request, payload)
        if existing:
            return existing
        _idempotency_key, correlation_id, actor_id, _request_hash = context
        customer = get_payment_provider().create_customer(payload, actor_id=actor_id, correlation_id=correlation_id)
        return persist_idempotent_response(context, {"customer": serialize_customer(customer), "correlation_id": correlation_id}, 201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except PaymentConflictError as exc:
        return error_response(exc.code, str(exc), 409)
    except InvalidPaymentPayloadError as exc:
        return error_response(exc.code, str(exc), 400)


@csrf_exempt
@require_POST
def mock_subscription_create(request):
    try:
        payload = load_payload(request)
        context, existing = begin_idempotent_change(request, payload)
        if existing:
            return existing
        _idempotency_key, correlation_id, actor_id, _request_hash = context
        subscription = get_payment_provider().create_subscription(payload, actor_id=actor_id, correlation_id=correlation_id)
        return persist_idempotent_response(context, {"subscription": serialize_subscription(subscription), "correlation_id": correlation_id}, 201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except MockPaymentCustomer.DoesNotExist:
        return error_response("PAYMENT_CUSTOMER_NOT_FOUND", "Mock payment customer was not found.", 404)
    except PaymentConflictError as exc:
        return error_response(exc.code, str(exc), 409)
    except InvalidPaymentPayloadError as exc:
        return error_response(exc.code, str(exc), 400)


@csrf_exempt
@require_POST
def mock_subscription_cancel(request, subscription_id):
    try:
        payload = load_payload(request)
        context, existing = begin_idempotent_change(request, payload)
        if existing:
            return existing
        _idempotency_key, correlation_id, actor_id, _request_hash = context
        subscription = get_payment_provider().cancel_subscription(str(subscription_id), actor_id=actor_id, correlation_id=correlation_id)
        return persist_idempotent_response(context, {"subscription": serialize_subscription(subscription), "correlation_id": correlation_id}, 200)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except MockPaymentSubscription.DoesNotExist:
        return error_response("PAYMENT_SUBSCRIPTION_NOT_FOUND", "Mock payment subscription was not found.", 404)
    except PaymentStateError as exc:
        return error_response(exc.code, str(exc), 409)
    except InvalidPaymentPayloadError as exc:
        return error_response(exc.code, str(exc), 400)


def mock_transaction_create(request, transaction_type: str):
    try:
        payload = load_payload(request)
        context, existing = begin_idempotent_change(request, payload)
        if existing:
            return existing
        _idempotency_key, correlation_id, actor_id, _request_hash = context
        provider = get_payment_provider()
        if transaction_type == "CHARGE":
            payment = provider.create_charge(payload, actor_id=actor_id, correlation_id=correlation_id)
        else:
            payment = provider.create_refund(payload, actor_id=actor_id, correlation_id=correlation_id)
        return persist_idempotent_response(context, {"transaction": serialize_transaction(payment), "correlation_id": correlation_id}, 201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except (MockPaymentCustomer.DoesNotExist, MockPaymentSubscription.DoesNotExist):
        return error_response("PAYMENT_REFERENCE_NOT_FOUND", "Mock payment customer or subscription was not found.", 404)
    except PaymentConflictError as exc:
        return error_response(exc.code, str(exc), 409)
    except InvalidPaymentPayloadError as exc:
        return error_response(exc.code, str(exc), 400)


@csrf_exempt
@require_POST
def mock_charge_create(request):
    return mock_transaction_create(request, "CHARGE")


@csrf_exempt
@require_POST
def mock_refund_create(request):
    return mock_transaction_create(request, "REFUND")


@csrf_exempt
@require_POST
def mock_webhook_receive(request):
    try:
        payload = load_payload(request)
        context, existing = begin_idempotent_change(request, payload)
        if existing:
            return existing
        _idempotency_key, correlation_id, actor_id, _request_hash = context
        event, created = get_payment_provider().receive_webhook(payload, actor_id=actor_id, correlation_id=correlation_id)
        status = 201 if created else 200
        return persist_idempotent_response(
            context,
            {"webhook_event": serialize_webhook_event(event), "created": created, "correlation_id": correlation_id},
            status,
        )
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except PaymentError as exc:
        return error_response(exc.code, str(exc), 400)
