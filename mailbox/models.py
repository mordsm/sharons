import uuid

from django.core.exceptions import ValidationError
from django.db import models


class MockEmailMessage(models.Model):
    class Classification(models.TextChoices):
        INFORMATION = "INFORMATION"
        TASK = "TASK"
        DECISION = "DECISION"
        INVOICE = "INVOICE"
        SPAM = "SPAM"
        PERSONAL_SENSITIVE = "PERSONAL_SENSITIVE"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.CharField(max_length=128, default="gmail_mock")
    external_event_id = models.CharField(max_length=200)
    sender = models.EmailField()
    subject = models.CharField(max_length=240)
    body = models.TextField()
    classification = models.CharField(max_length=32, choices=Classification.choices)
    proposed_action = models.JSONField(default=dict)
    rule_decision = models.CharField(max_length=32)
    rule_reason_codes = models.JSONField(default=list, blank=True)
    inbox_event_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["source", "external_event_id"], name="unique_mock_email_source_external_id"),
        ]

    def clean(self) -> None:
        if not self.source or not self.source.strip():
            raise ValidationError({"source": "Source cannot be empty."})
        if not self.external_event_id or not self.external_event_id.strip():
            raise ValidationError({"external_event_id": "External event ID cannot be empty."})
        if not self.subject or not self.subject.strip():
            raise ValidationError({"subject": "Subject cannot be empty."})
        if not isinstance(self.proposed_action, dict):
            raise ValidationError({"proposed_action": "Proposed action must be an object."})
        if not isinstance(self.rule_reason_codes, list):
            raise ValidationError({"rule_reason_codes": "Rule reason codes must be a list."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.source = self.source.strip()
        self.external_event_id = self.external_event_id.strip()
        self.subject = self.subject.strip()
        super().save(*args, **kwargs)
