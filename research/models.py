import uuid

from django.core.exceptions import ValidationError
from django.db import models

from operations.models import Task
from portfolio.models import Project, ProjectConnection


class ResearchTaskContract(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        READY = "READY"
        IN_PROGRESS = "IN_PROGRESS"
        COMPLETED = "COMPLETED"
        CANCELLED = "CANCELLED"

    class DepthMode(models.TextChoices):
        QUICK = "QUICK"
        STANDARD = "STANDARD"
        DEEP = "DEEP"
        SYSTEMATIC = "SYSTEMATIC"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.PROTECT, related_name="research_contracts")
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="research_contracts")
    project_connection = models.ForeignKey(ProjectConnection, on_delete=models.PROTECT, related_name="research_contracts")
    title = models.CharField(max_length=240)
    original_request = models.TextField()
    research_question = models.TextField()
    scope = models.JSONField(default=dict)
    deliverables = models.JSONField(default=list, blank=True)
    budgets = models.JSONField(default=dict, blank=True)
    safety_mode = models.CharField(max_length=32, default="STRICT_MEDICAL")
    depth_mode = models.CharField(max_length=16, choices=DepthMode.choices, default=DepthMode.DEEP)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.READY)
    created_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self) -> None:
        if not self.title or not self.title.strip():
            raise ValidationError({"title": "Title cannot be empty."})
        if not self.original_request or not self.original_request.strip():
            raise ValidationError({"original_request": "Original request cannot be empty."})
        if not self.research_question or not self.research_question.strip():
            raise ValidationError({"research_question": "Research question cannot be empty."})
        if not isinstance(self.scope, dict):
            raise ValidationError({"scope": "Scope must be an object."})
        if not isinstance(self.deliverables, list):
            raise ValidationError({"deliverables": "Deliverables must be a list."})
        if not isinstance(self.budgets, dict):
            raise ValidationError({"budgets": "Budgets must be an object."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.title = self.title.strip()
        self.original_request = self.original_request.strip()
        self.research_question = self.research_question.strip()
        self.safety_mode = self.safety_mode.strip() or "STRICT_MEDICAL"
        self.created_by = self.created_by.strip() or "api"
        super().save(*args, **kwargs)
