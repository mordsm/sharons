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


class ProductMilestone(models.Model):
    class Status(models.TextChoices):
        PLANNED = "PLANNED"
        ACTIVE = "ACTIVE"
        COMPLETED = "COMPLETED"
        DELAYED = "DELAYED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="milestones")
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    target_date = models.DateField()
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PLANNED)
    release_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["target_date", "created_at"]

    def clean(self) -> None:
        if not self.name or not self.name.strip():
            raise ValidationError({"name": "Milestone name cannot be empty."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.name = self.name.strip()
        self.description = self.description.strip()
        self.release_notes = self.release_notes.strip()
        super().save(*args, **kwargs)


class ProductFeature(models.Model):
    class Status(models.TextChoices):
        BACKLOG = "BACKLOG"
        PLANNED = "PLANNED"
        IN_PROGRESS = "IN_PROGRESS"
        COMPLETED = "COMPLETED"
        ARCHIVED = "ARCHIVED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="features")
    milestone = models.ForeignKey(ProductMilestone, on_delete=models.SET_NULL, null=True, blank=True, related_name="features")
    title = models.CharField(max_length=200)
    user_story = models.TextField(blank=True)
    acceptance_criteria = models.JSONField(default=list, blank=True)
    reach = models.PositiveIntegerField(default=100)
    impact = models.FloatField(default=1.0)
    confidence = models.FloatField(default=0.8)
    effort = models.FloatField(default=1.0)
    rice_score = models.FloatField(default=80.0)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.BACKLOG)
    created_by = models.CharField(max_length=128, default="product_manager")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-rice_score", "created_at"]

    def calculate_rice(self) -> float:
        eff = max(0.1, float(self.effort))
        score = (float(self.reach) * float(self.impact) * float(self.confidence)) / eff
        return round(score, 2)

    def clean(self) -> None:
        if not self.title or not self.title.strip():
            raise ValidationError({"title": "Feature title cannot be empty."})
        if self.effort <= 0:
            raise ValidationError({"effort": "Effort must be greater than 0."})

    def save(self, *args, **kwargs):
        self.rice_score = self.calculate_rice()
        self.full_clean()
        self.title = self.title.strip()
        self.user_story = self.user_story.strip()
        super().save(*args, **kwargs)


class ProductFeedback(models.Model):
    class Sentiment(models.TextChoices):
        POSITIVE = "POSITIVE"
        NEUTRAL = "NEUTRAL"
        NEGATIVE = "NEGATIVE"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="feedbacks")
    feature = models.ForeignKey(ProductFeature, on_delete=models.SET_NULL, null=True, blank=True, related_name="feedbacks")
    source = models.CharField(max_length=128)
    user_segment = models.CharField(max_length=64, default="General")
    content = models.TextField()
    sentiment = models.CharField(max_length=16, choices=Sentiment.choices, default=Sentiment.NEUTRAL)
    action_item = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self) -> None:
        if not self.source or not self.source.strip():
            raise ValidationError({"source": "Source cannot be empty."})
        if not self.content or not self.content.strip():
            raise ValidationError({"content": "Content cannot be empty."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.source = self.source.strip()
        self.content = self.content.strip()
        self.action_item = self.action_item.strip()
        super().save(*args, **kwargs)

