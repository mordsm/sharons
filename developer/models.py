import uuid

from django.core.exceptions import ValidationError
from django.db import models

from operations.models import Task
from portfolio.models import Project, ProjectConnection


class DeveloperWorkContract(models.Model):
    class Status(models.TextChoices):
        READY = "READY"
        IN_PROGRESS = "IN_PROGRESS"
        DELIVERED = "DELIVERED"
        CANCELLED = "CANCELLED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.PROTECT, related_name="developer_work_contracts")
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="developer_work_contracts")
    project_connection = models.ForeignKey(ProjectConnection, on_delete=models.PROTECT, related_name="developer_work_contracts")
    title = models.CharField(max_length=200)
    objective = models.TextField()
    scope = models.JSONField(default=list, blank=True)
    constraints = models.JSONField(default=dict, blank=True)
    acceptance_focus = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.READY)
    no_repo_write = models.BooleanField(default=True)
    no_deploy = models.BooleanField(default=True)
    created_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self) -> None:
        if not self.title or not self.title.strip():
            raise ValidationError({"title": "Title cannot be empty."})
        if not self.objective or not self.objective.strip():
            raise ValidationError({"objective": "Objective cannot be empty."})
        if not isinstance(self.scope, list):
            raise ValidationError({"scope": "Scope must be a list."})
        if not isinstance(self.constraints, dict):
            raise ValidationError({"constraints": "Constraints must be an object."})
        if not isinstance(self.acceptance_focus, list):
            raise ValidationError({"acceptance_focus": "Acceptance focus must be a list."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.title = self.title.strip()
        self.objective = self.objective.strip()
        self.created_by = self.created_by.strip() or "api"
        super().save(*args, **kwargs)


class ImplementationPlan(models.Model):
    class Status(models.TextChoices):
        NEEDS_REVIEW = "NEEDS_REVIEW"
        APPROVED = "APPROVED"
        DELIVERED_UNVERIFIED = "DELIVERED_UNVERIFIED"
        REJECTED = "REJECTED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contract = models.ForeignKey(DeveloperWorkContract, on_delete=models.PROTECT, related_name="implementation_plans")
    title = models.CharField(max_length=200)
    summary = models.TextField()
    planned_changes = models.JSONField(default=list)
    verification_plan = models.JSONField(default=list)
    risks = models.JSONField(default=list, blank=True)
    evidence = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.NEEDS_REVIEW)
    no_repo_write = models.BooleanField(default=True)
    no_deploy = models.BooleanField(default=True)
    created_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self) -> None:
        if not self.title or not self.title.strip():
            raise ValidationError({"title": "Title cannot be empty."})
        if not self.summary or not self.summary.strip():
            raise ValidationError({"summary": "Summary cannot be empty."})
        if not isinstance(self.planned_changes, list):
            raise ValidationError({"planned_changes": "Planned changes must be a list."})
        if not self.planned_changes:
            raise ValidationError({"planned_changes": "At least one planned change is required."})
        if not isinstance(self.verification_plan, list):
            raise ValidationError({"verification_plan": "Verification plan must be a list."})
        if not self.verification_plan:
            raise ValidationError({"verification_plan": "At least one verification step is required."})
        if not isinstance(self.risks, list):
            raise ValidationError({"risks": "Risks must be a list."})
        if not isinstance(self.evidence, list):
            raise ValidationError({"evidence": "Evidence must be a list."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.title = self.title.strip()
        self.summary = self.summary.strip()
        self.created_by = self.created_by.strip() or "api"
        super().save(*args, **kwargs)

