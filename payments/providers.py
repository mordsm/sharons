from abc import ABC, abstractmethod

from payments.models import MockPaymentCustomer, MockPaymentSubscription, MockPaymentTransaction, MockPaymentWebhookEvent
from payments.services import (
    cancel_mock_subscription,
    create_mock_customer,
    create_mock_subscription,
    create_mock_transaction,
    record_mock_webhook,
)


class PaymentProvider(ABC):
    @abstractmethod
    def create_customer(self, payload: dict, *, actor_id: str, correlation_id: str):
        raise NotImplementedError

    @abstractmethod
    def create_subscription(self, payload: dict, *, actor_id: str, correlation_id: str):
        raise NotImplementedError

    @abstractmethod
    def cancel_subscription(self, subscription_id: str, *, actor_id: str, correlation_id: str):
        raise NotImplementedError

    @abstractmethod
    def create_charge(self, payload: dict, *, actor_id: str, correlation_id: str):
        raise NotImplementedError

    @abstractmethod
    def create_refund(self, payload: dict, *, actor_id: str, correlation_id: str):
        raise NotImplementedError

    @abstractmethod
    def receive_webhook(self, payload: dict, *, actor_id: str, correlation_id: str):
        raise NotImplementedError


class MockPaymentProvider(PaymentProvider):
    provider_id = "mock"

    def create_customer(self, payload: dict, *, actor_id: str, correlation_id: str) -> MockPaymentCustomer:
        return create_mock_customer(payload, actor_id=actor_id, correlation_id=correlation_id)

    def create_subscription(self, payload: dict, *, actor_id: str, correlation_id: str) -> MockPaymentSubscription:
        return create_mock_subscription(payload, actor_id=actor_id, correlation_id=correlation_id)

    def cancel_subscription(self, subscription_id: str, *, actor_id: str, correlation_id: str) -> MockPaymentSubscription:
        return cancel_mock_subscription(subscription_id, actor_id=actor_id, correlation_id=correlation_id)

    def create_charge(self, payload: dict, *, actor_id: str, correlation_id: str) -> MockPaymentTransaction:
        return create_mock_transaction(
            payload,
            transaction_type=MockPaymentTransaction.TransactionType.CHARGE,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )

    def create_refund(self, payload: dict, *, actor_id: str, correlation_id: str) -> MockPaymentTransaction:
        return create_mock_transaction(
            payload,
            transaction_type=MockPaymentTransaction.TransactionType.REFUND,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )

    def receive_webhook(self, payload: dict, *, actor_id: str, correlation_id: str) -> tuple[MockPaymentWebhookEvent, bool]:
        return record_mock_webhook(payload, actor_id=actor_id, correlation_id=correlation_id)


def get_payment_provider(provider_id: str = "mock") -> PaymentProvider:
    if provider_id != "mock":
        raise ValueError("Only the mock payment provider is available.")
    return MockPaymentProvider()
