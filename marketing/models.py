import uuid

from django.core.exceptions import ValidationError
from django.db import models

from portfolio.models import Objective, Project


class MarketingRequest(models.Model):
    class Status(models.TextChoices):
        COMPLETED_DRAFT = "COMPLETED_DRAFT"
        NEEDS_INPUT = "NEEDS_INPUT"
        INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
        BLOCKED_DEPENDENCY = "BLOCKED_DEPENDENCY"
        AWAITING_APPROVAL = "AWAITING_APPROVAL"
        DATA_STALE = "DATA_STALE"
        TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
        REJECTED = "REJECTED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.PROTECT, related_name="marketing_requests")
    objective_record = models.ForeignKey(Objective, null=True, blank=True, on_delete=models.PROTECT, related_name="marketing_requests")
    objective_text = models.TextField(blank=True)
    geography = models.JSONField(default=list, blank=True)
    audiences = models.JSONField(default=list, blank=True)
    budget_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=8, blank=True)
    time_horizon = models.CharField(max_length=64, default="30 days")
    constraints = models.JSONField(default=list, blank=True)
    sources = models.JSONField(default=list, blank=True)
    inputs = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.COMPLETED_DRAFT)
    summary = models.TextField(blank=True)
    assumptions = models.JSONField(default=list, blank=True)
    risks = models.JSONField(default=list, blank=True)
    external_action_enabled = models.BooleanField(default=False)
    social_publish_enabled = models.BooleanField(default=False)
    email_send_enabled = models.BooleanField(default=False)
    ad_spend_enabled = models.BooleanField(default=False)
    correlation_id = models.CharField(max_length=128)
    created_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self) -> None:
        if self.external_action_enabled or self.social_publish_enabled or self.email_send_enabled or self.ad_spend_enabled:
            raise ValidationError("Marketing cannot publish, send, or spend.")
        if not isinstance(self.geography, list) or not isinstance(self.audiences, list):
            raise ValidationError("Geography and audiences must be lists.")
        if not isinstance(self.constraints, list) or not isinstance(self.sources, list) or not isinstance(self.inputs, dict):
            raise ValidationError("Constraints, sources, and inputs have an invalid shape.")
        if self.status not in self.Status.values:
            raise ValidationError({"status": "Status must be valid."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.objective_text = self.objective_text.strip()
        self.currency = self.currency.strip().upper()
        self.time_horizon = self.time_horizon.strip() or "30 days"
        self.created_by = self.created_by.strip() or "api"
        self.correlation_id = self.correlation_id.strip()
        super().save(*args, **kwargs)


class MarketingArtifact(models.Model):
    class ArtifactType(models.TextChoices):
        STRATEGY = "STRATEGY"
        ICP = "ICP"
        POSITIONING = "POSITIONING"
        CAMPAIGN_BRIEF = "CAMPAIGN_BRIEF"
        CREATIVE_DRAFT = "CREATIVE_DRAFT"
        EXPERIMENT = "EXPERIMENT"
        PERFORMANCE_REPORT = "PERFORMANCE_REPORT"
        DECISION_BUNDLE = "DECISION_BUNDLE"
        MANUAL_HANDOFF = "MANUAL_HANDOFF"

    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        IN_REVIEW = "IN_REVIEW"
        APPROVED_FOR_MANUAL_USE = "APPROVED_FOR_MANUAL_USE"
        REJECTED = "REJECTED"
        ARCHIVED = "ARCHIVED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.ForeignKey(MarketingRequest, on_delete=models.PROTECT, related_name="artifacts")
    artifact_type = models.CharField(max_length=32, choices=ArtifactType.choices)
    version = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.DRAFT)
    summary = models.TextField()
    content = models.JSONField(default=dict, blank=True)
    evidence = models.JSONField(default=list, blank=True)
    assumptions = models.JSONField(default=list, blank=True)
    risks = models.JSONField(default=list, blank=True)
    claims = models.JSONField(default=list, blank=True)
    owner = models.CharField(max_length=128, default="marketing")
    no_external_action = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["artifact_type", "version"]
        constraints = [
            models.UniqueConstraint(fields=["request", "artifact_type", "version"], name="unique_marketing_artifact_version"),
        ]

    def clean(self) -> None:
        if not self.summary or not self.summary.strip():
            raise ValidationError({"summary": "Summary cannot be empty."})
        if not self.no_external_action:
            raise ValidationError({"no_external_action": "Marketing artifacts cannot enable external actions."})
        for name in ("content", "evidence", "assumptions", "risks", "claims"):
            value = getattr(self, name)
            expected = dict if name == "content" else list
            if not isinstance(value, expected):
                raise ValidationError({name: f"{name} has an invalid shape."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.summary = self.summary.strip()
        self.owner = self.owner.strip() or "marketing"
        super().save(*args, **kwargs)


class MarketingReview(models.Model):
    class Decision(models.TextChoices):
        APPROVED = "APPROVED"
        REJECTED = "REJECTED"
        CHANGES_REQUESTED = "CHANGES_REQUESTED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    artifact = models.ForeignKey(MarketingArtifact, on_delete=models.PROTECT, related_name="reviews")
    artifact_version = models.PositiveIntegerField()
    decision = models.CharField(max_length=32, choices=Decision.choices)
    reason = models.TextField(blank=True)
    approver = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        self.approver = self.approver.strip() or "api"
        self.reason = self.reason.strip()
        super().save(*args, **kwargs)
