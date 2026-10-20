import uuid

from django.core.exceptions import ValidationError
from django.db import models


class MockPaymentCustomer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    external_customer_id = models.CharField(max_length=128, unique=True)
    email = models.EmailField()
    name = models.CharField(max_length=160, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self) -> None:
        if not self.external_customer_id or not self.external_customer_id.strip():
            raise ValidationError({"external_customer_id": "External customer ID cannot be empty."})
        if not isinstance(self.metadata, dict):
            raise ValidationError({"metadata": "Metadata must be an object."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.external_customer_id = self.external_customer_id.strip()
        self.email = self.email.strip()
        self.name = self.name.strip()
        self.created_by = self.created_by.strip() or "api"
        super().save(*args, **kwargs)


class MockPaymentSubscription(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        CANCELLED = "CANCELLED"

    class BillingInterval(models.TextChoices):
        MONTHLY = "MONTHLY"
        ANNUAL = "ANNUAL"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    external_subscription_id = models.CharField(max_length=128, unique=True)
    customer = models.ForeignKey(MockPaymentCustomer, on_delete=models.PROTECT, related_name="subscriptions")
    plan_name = models.CharField(max_length=120)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="ILS")
    billing_interval = models.CharField(max_length=16, choices=BillingInterval.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self) -> None:
        if self.amount <= 0:
            raise ValidationError({"amount": "Amount must be positive."})
        if not self.currency or len(self.currency.strip()) != 3:
            raise ValidationError({"currency": "Currency must be a 3-letter code."})
        if self.billing_interval not in self.BillingInterval.values:
            raise ValidationError({"billing_interval": "Billing interval must be valid."})
        if not isinstance(self.metadata, dict):
            raise ValidationError({"metadata": "Metadata must be an object."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.external_subscription_id = self.external_subscription_id.strip()
        self.plan_name = self.plan_name.strip()
        self.currency = self.currency.strip().upper()
        self.created_by = self.created_by.strip() or "api"
        super().save(*args, **kwargs)


class MockPaymentTransaction(models.Model):
    class TransactionType(models.TextChoices):
        CHARGE = "CHARGE"
        REFUND = "REFUND"

    class Status(models.TextChoices):
        SUCCEEDED = "SUCCEEDED"
        FAILED = "FAILED"
        TIMEOUT = "TIMEOUT"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    external_transaction_id = models.CharField(max_length=128, unique=True)
    customer = models.ForeignKey(MockPaymentCustomer, on_delete=models.PROTECT, related_name="transactions")
    subscription = models.ForeignKey(MockPaymentSubscription, on_delete=models.PROTECT, null=True, blank=True, related_name="transactions")
    transaction_type = models.CharField(max_length=16, choices=TransactionType.choices)
    status = models.CharField(max_length=16, choices=Status.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="ILS")
    reason = models.CharField(max_length=200, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self) -> None:
        if self.amount <= 0:
            raise ValidationError({"amount": "Amount must be positive."})
        if not self.currency or len(self.currency.strip()) != 3:
            raise ValidationError({"currency": "Currency must be a 3-letter code."})
        if not isinstance(self.metadata, dict):
            raise ValidationError({"metadata": "Metadata must be an object."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.external_transaction_id = self.external_transaction_id.strip()
        self.currency = self.currency.strip().upper()
        self.reason = self.reason.strip()
        self.created_by = self.created_by.strip() or "api"
        super().save(*args, **kwargs)


class MockPaymentWebhookEvent(models.Model):
    class Status(models.TextChoices):
        RECEIVED = "RECEIVED"
        DUPLICATE = "DUPLICATE"
        OUT_OF_ORDER = "OUT_OF_ORDER"
        UNSUPPORTED = "UNSUPPORTED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.CharField(max_length=128, default="mock_payment")
    external_event_id = models.CharField(max_length=200)
    event_type = models.CharField(max_length=80)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.RECEIVED)
    correlation_id = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["source", "external_event_id"], name="unique_mock_payment_source_external_event"),
        ]

    def clean(self) -> None:
        if not self.source or not self.source.strip():
            raise ValidationError({"source": "Source cannot be empty."})
        if not self.external_event_id or not self.external_event_id.strip():
            raise ValidationError({"external_event_id": "External event ID cannot be empty."})
        if not self.event_type or not self.event_type.strip():
            raise ValidationError({"event_type": "Event type cannot be empty."})
        if not isinstance(self.payload, dict):
            raise ValidationError({"payload": "Payload must be an object."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.source = self.source.strip()
        self.external_event_id = self.external_event_id.strip()
        self.event_type = self.event_type.strip()
        self.correlation_id = self.correlation_id.strip()
        super().save(*args, **kwargs)
