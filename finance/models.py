import uuid

from django.core.exceptions import ValidationError
from django.db import models


class FinancialRecord(models.Model):
    class RecordType(models.TextChoices):
        INCOME = "INCOME"
        EXPENSE = "EXPENSE"
        SUBSCRIPTION_COST = "SUBSCRIPTION_COST"
        SERVER_COST = "SERVER_COST"
        API_COST = "API_COST"
        OTHER_COST = "OTHER_COST"

    class ReconciliationStatus(models.TextChoices):
        UNRECONCILED = "UNRECONCILED"
        RECONCILED = "RECONCILED"
        DISCREPANCY = "DISCREPANCY"
        NEEDS_REVIEW = "NEEDS_REVIEW"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    record_type = models.CharField(max_length=32, choices=RecordType.choices)
    occurred_on = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="ILS")
    source = models.CharField(max_length=128)
    category = models.CharField(max_length=128, blank=True)
    description = models.CharField(max_length=240)
    external_reference = models.CharField(max_length=200, blank=True)
    reconciliation_status = models.CharField(
        max_length=32,
        choices=ReconciliationStatus.choices,
        default=ReconciliationStatus.UNRECONCILED,
    )
    reconciliation_notes = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-occurred_on", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "external_reference"],
                condition=~models.Q(external_reference=""),
                name="unique_financial_external_reference_per_source",
            )
        ]

    def clean(self) -> None:
        if self.record_type not in self.RecordType.values:
            raise ValidationError({"record_type": "Record type must be valid."})
        if self.amount <= 0:
            raise ValidationError({"amount": "Amount must be positive."})
        if not self.currency or len(self.currency.strip()) != 3:
            raise ValidationError({"currency": "Currency must be a 3-letter code."})
        if not self.source or not self.source.strip():
            raise ValidationError({"source": "Source cannot be empty."})
        if not self.description or not self.description.strip():
            raise ValidationError({"description": "Description cannot be empty."})
        if not isinstance(self.metadata, dict):
            raise ValidationError({"metadata": "Metadata must be an object."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.currency = self.currency.strip().upper()
        self.source = self.source.strip()
        self.category = self.category.strip()
        self.description = self.description.strip()
        self.external_reference = self.external_reference.strip()
        self.created_by = self.created_by.strip() or "api"
        super().save(*args, **kwargs)
