import uuid

from django.core.exceptions import ValidationError
from django.db import models

from operations.models import Task


class VerificationReview(models.Model):
    class Decision(models.TextChoices):
        ACCEPTED = "ACCEPTED"
        REJECTED = "REJECTED"
        NEEDS_MORE_EVIDENCE = "NEEDS_MORE_EVIDENCE"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.PROTECT, related_name="verification_reviews")
    decision = models.CharField(max_length=32, choices=Decision.choices)
    notes = models.TextField(blank=True)
    evidence_ids = models.JSONField(default=list, blank=True)
    no_external_action = models.BooleanField(default=True)
    reviewed_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self) -> None:
        if self.decision not in self.Decision.values:
            raise ValidationError({"decision": "Decision must be valid."})
        if not isinstance(self.evidence_ids, list):
            raise ValidationError({"evidence_ids": "Evidence IDs must be a list."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.notes = self.notes.strip()
        self.reviewed_by = self.reviewed_by.strip() or "qa_agent"
        super().save(*args, **kwargs)
