import json

import pytest

from governance.models import AuditEvent
from payments.models import MockPaymentCustomer, MockPaymentSubscription, MockPaymentTransaction, MockPaymentWebhookEvent
from payments.providers import MockPaymentProvider, PaymentProvider, get_payment_provider


pytestmark = pytest.mark.django_db


def headers(key: str, correlation: str = "corr-payments-1") -> dict:
    return {"Idempotency-Key": key, "X-Correlation-ID": correlation, "X-Actor-ID": "finance_agent"}


def create_customer(client) -> MockPaymentCustomer:
    payload = {
        "external_customer_id": "cus_mock_1",
        "email": "buyer@example.com",
        "name": "Beta Buyer",
        "metadata": {"source": "test"},
    }
    response = client.post(
        "/api/v1/payments/mock/customers/create/",
        data=json.dumps(payload),
        content_type="application/json",
        headers=headers("payment-customer-1"),
    )
    assert response.status_code == 201
    return MockPaymentCustomer.objects.get(external_customer_id="cus_mock_1")


def create_subscription(client, customer: MockPaymentCustomer) -> MockPaymentSubscription:
    payload = {
        "customer_id": str(customer.id),
        "external_subscription_id": "sub_mock_1",
        "plan_name": "Mental Trainer monthly",
        "amount": "49.00",
        "currency": "ILS",
        "billing_interval": MockPaymentSubscription.BillingInterval.MONTHLY,
    }
    response = client.post(
        "/api/v1/payments/mock/subscriptions/create/",
        data=json.dumps(payload),
        content_type="application/json",
        headers=headers("payment-subscription-1"),
    )
    assert response.status_code == 201
    return MockPaymentSubscription.objects.get(external_subscription_id="sub_mock_1")


def test_create_mock_customer_is_idempotent_and_audited(client):
    payload = {"external_customer_id": "cus_mock_1", "email": "buyer@example.com"}
    first = client.post(
        "/api/v1/payments/mock/customers/create/",
        data=json.dumps(payload),
        content_type="application/json",
        headers=headers("payment-customer-1"),
    )
    second = client.post(
        "/api/v1/payments/mock/customers/create/",
        data=json.dumps(payload),
        content_type="application/json",
        headers=headers("payment-customer-1"),
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert MockPaymentCustomer.objects.count() == 1
    assert AuditEvent.objects.filter(action="payments.mock.customer.created").count() == 1


def test_create_subscription_and_successful_charge(client):
    customer = create_customer(client)
    subscription = create_subscription(client, customer)

    payload = {
        "customer_id": str(customer.id),
        "subscription_id": str(subscription.id),
        "external_transaction_id": "txn_charge_1",
        "amount": "49.00",
        "currency": "ILS",
        "status": MockPaymentTransaction.Status.SUCCEEDED,
    }
    response = client.post(
        "/api/v1/payments/mock/charges/create/",
        data=json.dumps(payload),
        content_type="application/json",
        headers=headers("payment-charge-1"),
    )

    assert response.status_code == 201
    transaction = MockPaymentTransaction.objects.get(external_transaction_id="txn_charge_1")
    assert transaction.transaction_type == MockPaymentTransaction.TransactionType.CHARGE
    assert transaction.status == MockPaymentTransaction.Status.SUCCEEDED
    assert AuditEvent.objects.filter(action="payments.mock.transaction.charge").exists()


def test_provider_contract_resolves_only_mock_provider():
    provider = get_payment_provider()

    assert isinstance(provider, PaymentProvider)
    assert isinstance(provider, MockPaymentProvider)
    with pytest.raises(ValueError):
        get_payment_provider("real_provider")


def test_mock_provider_can_simulate_failed_and_timeout_charges(client):
    customer = create_customer(client)
    provider = MockPaymentProvider()

    failed = provider.create_charge(
        {
            "customer_id": str(customer.id),
            "external_transaction_id": "txn_failed_1",
            "amount": "49.00",
            "status": MockPaymentTransaction.Status.FAILED,
            "reason": "card_declined",
        },
        actor_id="finance_agent",
        correlation_id="corr-provider-failed",
    )
    timeout = provider.create_charge(
        {
            "customer_id": str(customer.id),
            "external_transaction_id": "txn_timeout_1",
            "amount": "49.00",
            "status": MockPaymentTransaction.Status.TIMEOUT,
            "reason": "gateway_timeout",
        },
        actor_id="finance_agent",
        correlation_id="corr-provider-timeout",
    )

    assert failed.status == MockPaymentTransaction.Status.FAILED
    assert timeout.status == MockPaymentTransaction.Status.TIMEOUT


def test_cancel_subscription(client):
    customer = create_customer(client)
    subscription = create_subscription(client, customer)

    response = client.post(
        f"/api/v1/payments/mock/subscriptions/{subscription.id}/cancel/",
        data=json.dumps({"reason": "customer_request"}),
        content_type="application/json",
        headers=headers("payment-cancel-1"),
    )

    assert response.status_code == 200
    subscription.refresh_from_db()
    assert subscription.status == MockPaymentSubscription.Status.CANCELLED
    assert AuditEvent.objects.filter(action="payments.mock.subscription.cancelled").exists()


def test_refund_endpoint_creates_refund_transaction(client):
    customer = create_customer(client)

    payload = {
        "customer_id": str(customer.id),
        "external_transaction_id": "txn_refund_1",
        "amount": "49.00",
        "currency": "ILS",
        "status": MockPaymentTransaction.Status.SUCCEEDED,
        "reason": "customer_request",
    }
    response = client.post(
        "/api/v1/payments/mock/refunds/create/",
        data=json.dumps(payload),
        content_type="application/json",
        headers=headers("payment-refund-1"),
    )

    assert response.status_code == 201
    transaction = MockPaymentTransaction.objects.get(external_transaction_id="txn_refund_1")
    assert transaction.transaction_type == MockPaymentTransaction.TransactionType.REFUND
    assert AuditEvent.objects.filter(action="payments.mock.transaction.refund").exists()


def test_duplicate_webhook_returns_idempotent_response(client):
    payload = {
        "source": "mock_payment",
        "external_event_id": "evt_1",
        "event_type": "charge.succeeded",
        "payload": {"external_transaction_id": "txn_charge_1"},
    }
    first = client.post(
        "/api/v1/payments/mock/webhooks/",
        data=json.dumps(payload),
        content_type="application/json",
        headers=headers("payment-webhook-1"),
    )
    second = client.post(
        "/api/v1/payments/mock/webhooks/",
        data=json.dumps(payload),
        content_type="application/json",
        headers=headers("payment-webhook-1"),
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert MockPaymentWebhookEvent.objects.count() == 1


def test_out_of_order_subscription_webhook_is_recorded_without_external_action(client):
    payload = {
        "source": "mock_payment",
        "external_event_id": "evt_cancel_before_subscription",
        "event_type": "subscription.cancelled",
        "payload": {"external_subscription_id": "missing_sub"},
    }
    response = client.post(
        "/api/v1/payments/mock/webhooks/",
        data=json.dumps(payload),
        content_type="application/json",
        headers=headers("payment-webhook-2"),
    )

    assert response.status_code == 201
    event = MockPaymentWebhookEvent.objects.get(external_event_id="evt_cancel_before_subscription")
    assert event.status == MockPaymentWebhookEvent.Status.OUT_OF_ORDER
    assert AuditEvent.objects.filter(action="payments.mock.webhook.received", object_id=str(event.id)).exists()
