from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from governance.models import AuditEvent
from payments.models import MockPaymentCustomer, MockPaymentSubscription, MockPaymentTransaction, MockPaymentWebhookEvent


class PaymentError(Exception):
    code = "PAYMENT_ERROR"


class InvalidPaymentPayloadError(PaymentError):
    code = "INVALID_PAYMENT_PAYLOAD"


class PaymentConflictError(PaymentError):
    code = "PAYMENT_CONFLICT"


class PaymentStateError(PaymentError):
    code = "PAYMENT_STATE_ERROR"


def parse_amount(value) -> Decimal:
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise InvalidPaymentPayloadError("amount must be a decimal number.") from exc
    if amount <= 0:
        raise InvalidPaymentPayloadError("amount must be positive.")
    return amount


def serialize_customer(customer: MockPaymentCustomer) -> dict:
    return {
        "id": str(customer.id),
        "external_customer_id": customer.external_customer_id,
        "email": customer.email,
        "name": customer.name,
        "metadata": customer.metadata,
        "created_by": customer.created_by,
        "created_at": customer.created_at.isoformat(),
    }


def serialize_subscription(subscription: MockPaymentSubscription) -> dict:
    return {
        "id": str(subscription.id),
        "external_subscription_id": subscription.external_subscription_id,
        "customer_id": str(subscription.customer_id),
        "plan_name": subscription.plan_name,
        "amount": str(subscription.amount),
        "currency": subscription.currency,
        "billing_interval": subscription.billing_interval,
        "status": subscription.status,
        "metadata": subscription.metadata,
        "created_by": subscription.created_by,
        "created_at": subscription.created_at.isoformat(),
        "updated_at": subscription.updated_at.isoformat(),
    }


def serialize_transaction(payment: MockPaymentTransaction) -> dict:
    return {
        "id": str(payment.id),
        "external_transaction_id": payment.external_transaction_id,
        "customer_id": str(payment.customer_id),
        "subscription_id": str(payment.subscription_id) if payment.subscription_id else None,
        "transaction_type": payment.transaction_type,
        "status": payment.status,
        "amount": str(payment.amount),
        "currency": payment.currency,
        "reason": payment.reason,
        "metadata": payment.metadata,
        "created_by": payment.created_by,
        "created_at": payment.created_at.isoformat(),
    }


def serialize_webhook_event(event: MockPaymentWebhookEvent) -> dict:
    return {
        "id": str(event.id),
        "source": event.source,
        "external_event_id": event.external_event_id,
        "event_type": event.event_type,
        "payload": event.payload,
        "status": event.status,
        "correlation_id": event.correlation_id,
        "created_at": event.created_at.isoformat(),
    }


def create_mock_customer(payload: dict, *, actor_id: str, correlation_id: str) -> MockPaymentCustomer:
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise InvalidPaymentPayloadError("metadata must be an object.")
    actor = actor_id.strip() or "api"
    with transaction.atomic():
        try:
            customer = MockPaymentCustomer.objects.create(
                external_customer_id=str(payload.get("external_customer_id", "")).strip(),
                email=str(payload.get("email", "")).strip(),
                name=str(payload.get("name", "")).strip(),
                metadata=metadata,
                created_by=actor,
            )
        except (IntegrityError, ValidationError) as exc:
            raise PaymentConflictError("Mock payment customer already exists or is invalid.") from exc
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="payments.mock.customer.created",
            object_type="payments.MockPaymentCustomer",
            object_id=str(customer.id),
            correlation_id=correlation_id,
            metadata={"external_customer_id": customer.external_customer_id},
        )
    return customer


def create_mock_subscription(payload: dict, *, actor_id: str, correlation_id: str) -> MockPaymentSubscription:
    metadata = payload.get("metadata", {})
    billing_interval = str(payload.get("billing_interval", "")).strip()
    if billing_interval not in MockPaymentSubscription.BillingInterval.values:
        raise InvalidPaymentPayloadError("billing_interval must be MONTHLY or ANNUAL.")
    if not isinstance(metadata, dict):
        raise InvalidPaymentPayloadError("metadata must be an object.")
    actor = actor_id.strip() or "api"
    with transaction.atomic():
        customer = MockPaymentCustomer.objects.select_for_update().get(id=str(payload.get("customer_id", "")).strip())
        try:
            subscription = MockPaymentSubscription.objects.create(
                external_subscription_id=str(payload.get("external_subscription_id", "")).strip(),
                customer=customer,
                plan_name=str(payload.get("plan_name", "")).strip(),
                amount=parse_amount(payload.get("amount", "")),
                currency=str(payload.get("currency", "ILS")).strip().upper(),
                billing_interval=billing_interval,
                metadata=metadata,
                created_by=actor,
            )
        except (IntegrityError, ValidationError) as exc:
            raise PaymentConflictError("Mock payment subscription already exists or is invalid.") from exc
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="payments.mock.subscription.created",
            object_type="payments.MockPaymentSubscription",
            object_id=str(subscription.id),
            correlation_id=correlation_id,
            metadata={"external_subscription_id": subscription.external_subscription_id, "customer_id": str(customer.id)},
        )
    return subscription


def cancel_mock_subscription(subscription_id: str, *, actor_id: str, correlation_id: str) -> MockPaymentSubscription:
    actor = actor_id.strip() or "api"
    with transaction.atomic():
        subscription = MockPaymentSubscription.objects.select_for_update().get(id=subscription_id)
        if subscription.status == MockPaymentSubscription.Status.CANCELLED:
            raise PaymentStateError("Subscription is already cancelled.")
        subscription.status = MockPaymentSubscription.Status.CANCELLED
        subscription.save(update_fields=["status", "updated_at"])
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="payments.mock.subscription.cancelled",
            object_type="payments.MockPaymentSubscription",
            object_id=str(subscription.id),
            correlation_id=correlation_id,
            metadata={"external_subscription_id": subscription.external_subscription_id},
        )
    return subscription


def create_mock_transaction(payload: dict, *, transaction_type: str, actor_id: str, correlation_id: str) -> MockPaymentTransaction:
    metadata = payload.get("metadata", {})
    status = str(payload.get("status", MockPaymentTransaction.Status.SUCCEEDED)).strip()
    if status not in MockPaymentTransaction.Status.values:
        raise InvalidPaymentPayloadError("status must be SUCCEEDED, FAILED or TIMEOUT.")
    if not isinstance(metadata, dict):
        raise InvalidPaymentPayloadError("metadata must be an object.")
    actor = actor_id.strip() or "api"
    with transaction.atomic():
        customer = MockPaymentCustomer.objects.select_for_update().get(id=str(payload.get("customer_id", "")).strip())
        subscription_id = str(payload.get("subscription_id", "")).strip()
        subscription = MockPaymentSubscription.objects.select_for_update().get(id=subscription_id) if subscription_id else None
        try:
            payment = MockPaymentTransaction.objects.create(
                external_transaction_id=str(payload.get("external_transaction_id", "")).strip(),
                customer=customer,
                subscription=subscription,
                transaction_type=transaction_type,
                status=status,
                amount=parse_amount(payload.get("amount", "")),
                currency=str(payload.get("currency", "ILS")).strip().upper(),
                reason=str(payload.get("reason", "")).strip(),
                metadata=metadata,
                created_by=actor,
            )
        except (IntegrityError, ValidationError) as exc:
            raise PaymentConflictError("Mock payment transaction already exists or is invalid.") from exc
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action=f"payments.mock.transaction.{transaction_type.lower()}",
            object_type="payments.MockPaymentTransaction",
            object_id=str(payment.id),
            correlation_id=correlation_id,
            metadata={"external_transaction_id": payment.external_transaction_id, "transaction_type": payment.transaction_type, "status": payment.status},
        )
    return payment


def record_mock_webhook(payload: dict, *, actor_id: str, correlation_id: str) -> tuple[MockPaymentWebhookEvent, bool]:
    source = str(payload.get("source", "mock_payment")).strip()
    external_event_id = str(payload.get("external_event_id", "")).strip()
    event_type = str(payload.get("event_type", "")).strip()
    event_payload = payload.get("payload", {})
    if not source or not external_event_id or not event_type:
        raise InvalidPaymentPayloadError("source, external_event_id and event_type are required.")
    if not isinstance(event_payload, dict):
        raise InvalidPaymentPayloadError("payload must be an object.")
    actor = actor_id.strip() or "api"
    with transaction.atomic():
        existing = MockPaymentWebhookEvent.objects.filter(source=source, external_event_id=external_event_id).first()
        if existing:
            return existing, False
        status = MockPaymentWebhookEvent.Status.RECEIVED
        if event_type == "subscription.cancelled" and not MockPaymentSubscription.objects.filter(
            external_subscription_id=str(event_payload.get("external_subscription_id", "")).strip()
        ).exists():
            status = MockPaymentWebhookEvent.Status.OUT_OF_ORDER
        elif event_type not in {"charge.succeeded", "charge.failed", "charge.timeout", "subscription.cancelled", "refund.succeeded"}:
            status = MockPaymentWebhookEvent.Status.UNSUPPORTED
        event = MockPaymentWebhookEvent.objects.create(
            source=source,
            external_event_id=external_event_id,
            event_type=event_type,
            payload=event_payload,
            status=status,
            correlation_id=correlation_id,
        )
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="payments.mock.webhook.received",
            object_type="payments.MockPaymentWebhookEvent",
            object_id=str(event.id),
            correlation_id=correlation_id,
            metadata={"source": source, "external_event_id": external_event_id, "event_type": event_type, "status": status},
        )
    return event, True
