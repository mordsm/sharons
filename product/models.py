import uuid

from django.core.exceptions import ValidationError
from django.db import models

from operations.models import Task
from portfolio.models import Project, ProjectConnection


class ProductSpecContract(models.Model):
    class Status(models.TextChoices):
        READY = "READY"
        IN_PROGRESS = "IN_PROGRESS"
        COMPLETED = "COMPLETED"
        CANCELLED = "CANCELLED"

    class SpecType(models.TextChoices):
        PRD = "PRD"
        USER_STORY = "USER_STORY"
        ROADMAP = "ROADMAP"
        RELEASE_SCOPE = "RELEASE_SCOPE"
        DISCOVERY_BRIEF = "DISCOVERY_BRIEF"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.PROTECT, related_name="product_spec_contracts")
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="product_spec_contracts")
    project_connection = models.ForeignKey(ProjectConnection, on_delete=models.PROTECT, related_name="product_spec_contracts")
    title = models.CharField(max_length=200)
    spec_type = models.CharField(max_length=32, choices=SpecType.choices, default=SpecType.PRD)
    objective = models.TextField()
    target_users = models.JSONField(default=list, blank=True)
    problem_statement = models.TextField()
    success_metrics = models.JSONField(default=list, blank=True)
    requirements = models.JSONField(default=list, blank=True)
    constraints = models.JSONField(default=dict, blank=True)
    open_questions = models.JSONField(default=list, blank=True)
    deliverables = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.READY)
    no_external_write = models.BooleanField(default=True)
    created_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self) -> None:
        if not self.title or not self.title.strip():
            raise ValidationError({"title": "Title cannot be empty."})
        if not self.objective or not self.objective.strip():
            raise ValidationError({"objective": "Objective cannot be empty."})
        if not self.problem_statement or not self.problem_statement.strip():
            raise ValidationError({"problem_statement": "Problem statement cannot be empty."})
        if not isinstance(self.target_users, list):
            raise ValidationError({"target_users": "Target users must be a list."})
        if not isinstance(self.success_metrics, list):
            raise ValidationError({"success_metrics": "Success metrics must be a list."})
        if not isinstance(self.requirements, list):
            raise ValidationError({"requirements": "Requirements must be a list."})
        if not isinstance(self.constraints, dict):
            raise ValidationError({"constraints": "Constraints must be an object."})
        if not isinstance(self.open_questions, list):
            raise ValidationError({"open_questions": "Open questions must be a list."})
        if not isinstance(self.deliverables, list):
            raise ValidationError({"deliverables": "Deliverables must be a list."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.title = self.title.strip()
        self.objective = self.objective.strip()
        self.problem_statement = self.problem_statement.strip()
        self.created_by = self.created_by.strip() or "api"
        super().save(*args, **kwargs)


class ProductSpecDraft(models.Model):
    class ReviewStatus(models.TextChoices):
        NEEDS_REVIEW = "NEEDS_REVIEW"
        APPROVED = "APPROVED"
        REJECTED = "REJECTED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contract = models.ForeignKey(ProductSpecContract, on_delete=models.PROTECT, related_name="drafts")
    title = models.CharField(max_length=200)
    content = models.JSONField(default=dict)
    assumptions = models.JSONField(default=list, blank=True)
    risks = models.JSONField(default=list, blank=True)
    review_status = models.CharField(max_length=16, choices=ReviewStatus.choices, default=ReviewStatus.NEEDS_REVIEW)
    no_external_write = models.BooleanField(default=True)
    created_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self) -> None:
        if not self.title or not self.title.strip():
            raise ValidationError({"title": "Title cannot be empty."})
        if not isinstance(self.content, dict):
            raise ValidationError({"content": "Content must be an object."})
        if not isinstance(self.assumptions, list):
            raise ValidationError({"assumptions": "Assumptions must be a list."})
        if not isinstance(self.risks, list):
            raise ValidationError({"risks": "Risks must be a list."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.title = self.title.strip()
        self.created_by = self.created_by.strip() or "api"
        super().save(*args, **kwargs)
