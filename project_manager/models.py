import uuid

from django.core.exceptions import ValidationError
from django.db import models

from operations.models import Task
from portfolio.models import Objective


class ExecutionReview(models.Model):
    class Status(models.TextChoices):
        READY = "READY"
        ARCHIVED = "ARCHIVED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    objective = models.ForeignKey(Objective, on_delete=models.PROTECT, related_name="execution_reviews")
    summary = models.TextField()
    health_status = models.CharField(max_length=32)
    risks = models.JSONField(default=list, blank=True)
    recommendations = models.JSONField(default=list, blank=True)
    task_snapshot = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.READY)
    no_external_action = models.BooleanField(default=True)
    created_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self) -> None:
        if not self.summary or not self.summary.strip():
            raise ValidationError({"summary": "Summary cannot be empty."})
        if not isinstance(self.risks, list):
            raise ValidationError({"risks": "Risks must be a list."})
        if not isinstance(self.recommendations, list):
            raise ValidationError({"recommendations": "Recommendations must be a list."})
        if not isinstance(self.task_snapshot, dict):
            raise ValidationError({"task_snapshot": "Task snapshot must be an object."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.summary = self.summary.strip()
        self.created_by = self.created_by.strip() or "api"
        super().save(*args, **kwargs)


class MilestoneProposal(models.Model):
    class Status(models.TextChoices):
        PROPOSED = "PROPOSED"
        ACCEPTED = "ACCEPTED"
        DISMISSED = "DISMISSED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    objective = models.ForeignKey(Objective, on_delete=models.PROTECT, related_name="milestone_proposals")
    task = models.ForeignKey(Task, on_delete=models.PROTECT, related_name="milestone_proposals")
    title = models.CharField(max_length=240)
    rationale = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PROPOSED)
    no_external_action = models.BooleanField(default=True)
    created_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class BlockerReview(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.PROTECT, related_name="blocker_reviews")
    blocker_summary = models.TextField()
    recommended_action = models.CharField(max_length=64)
    escalation_required = models.BooleanField(default=False)
    no_external_action = models.BooleanField(default=True)
    created_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self) -> None:
        if not self.blocker_summary or not self.blocker_summary.strip():
            raise ValidationError({"blocker_summary": "Blocker summary cannot be empty."})
        if not self.recommended_action or not self.recommended_action.strip():
            raise ValidationError({"recommended_action": "Recommended action cannot be empty."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.blocker_summary = self.blocker_summary.strip()
        self.recommended_action = self.recommended_action.strip()
        self.created_by = self.created_by.strip() or "api"
        super().save(*args, **kwargs)

