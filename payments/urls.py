from django.urls import path

from payments.views import (
    mock_charge_create,
    mock_customer_create,
    mock_refund_create,
    mock_subscription_cancel,
    mock_subscription_create,
    mock_webhook_receive,
)


urlpatterns = [
    path("mock/customers/create/", mock_customer_create, name="mock-payment-customer-create"),
    path("mock/subscriptions/create/", mock_subscription_create, name="mock-payment-subscription-create"),
    path("mock/subscriptions/<uuid:subscription_id>/cancel/", mock_subscription_cancel, name="mock-payment-subscription-cancel"),
    path("mock/charges/create/", mock_charge_create, name="mock-payment-charge-create"),
    path("mock/refunds/create/", mock_refund_create, name="mock-payment-refund-create"),
    path("mock/webhooks/", mock_webhook_receive, name="mock-payment-webhook"),
]
