import uuid

from django.core.exceptions import ValidationError
from django.db import models



class Project(models.Model):
    class Status(models.TextChoices):
        IDEA = "IDEA"
        DISCOVERY = "DISCOVERY"
        ACTIVE = "ACTIVE"
        PAUSED = "PAUSED"
        ARCHIVED = "ARCHIVED"

    class DataClassification(models.TextChoices):
        PUBLIC = "PUBLIC"
        INTERNAL = "INTERNAL"
        CONFIDENTIAL = "CONFIDENTIAL"
        PERSONAL_SENSITIVE = "PERSONAL_SENSITIVE"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.IDEA)
    repository_provider = models.CharField(max_length=64, blank=True)
    repository_reference = models.CharField(max_length=500, blank=True)
    default_branch = models.CharField(max_length=128, blank=True)
    owner = models.CharField(max_length=128)
    data_classification = models.CharField(
        max_length=32,
        choices=DataClassification.choices,
        default=DataClassification.INTERNAL,
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class ProjectConnection(models.Model):
    class ConnectionType(models.TextChoices):
        REPOSITORY = "REPOSITORY"
        ISSUE_TRACKER = "ISSUE_TRACKER"
        CI = "CI"
        DEPLOYMENT = "DEPLOYMENT"
        PRODUCT_API = "PRODUCT_API"

    class PermissionMode(models.TextChoices):
        READ_ONLY = "READ_ONLY"
        PROPOSE_CHANGES = "PROPOSE_CHANGES"
        WRITE_APPROVED = "WRITE_APPROVED"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="connections")
    connection_type = models.CharField(max_length=32, choices=ConnectionType.choices)
    adapter_type = models.CharField(max_length=128)
    capabilities = models.JSONField(default=dict, blank=True)
    permission_mode = models.CharField(max_length=32, choices=PermissionMode.choices, default=PermissionMode.READ_ONLY)
    credential_reference = models.CharField(max_length=256, blank=True)
    contract_version = models.PositiveIntegerField(default=1)
    active = models.BooleanField(default=True)


class StrategyVersion(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        ACTIVE = "ACTIVE"
        SUPERSEDED = "SUPERSEDED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version = models.PositiveIntegerField(unique=True)
    title = models.CharField(max_length=200)
    content = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    approved_by = models.CharField(max_length=128, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)


class Objective(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        ACTIVE = "ACTIVE"
        CLOSED = "CLOSED"
        PAUSED = "PAUSED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=32, unique=True)
    strategy_version = models.ForeignKey(StrategyVersion, on_delete=models.PROTECT, related_name="objectives")
    name = models.CharField(max_length=200)
    business_outcome = models.TextField()
    due_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    owner_agent_id = models.CharField(max_length=128, blank=True)
    weight = models.PositiveSmallIntegerField(default=1)


class ObjectiveProjectLink(models.Model):
    class Role(models.TextChoices):
        PRIMARY = "PRIMARY"
        SUPPORTING = "SUPPORTING"
        DATA_SOURCE = "DATA_SOURCE"

    objective = models.ForeignKey(Objective, on_delete=models.CASCADE, related_name="project_links")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="objective_links")
    role = models.CharField(max_length=32, choices=Role.choices, default=Role.SUPPORTING)
    rationale = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["objective", "project"], name="unique_objective_project_link"),
        ]


class ProjectStateAssessment(models.Model):
    class Status(models.TextChoices):
        CURRENT = "CURRENT"
        SUPERSEDED = "SUPERSEDED"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="state_assessments")
    objective = models.ForeignKey(Objective, on_delete=models.PROTECT, related_name="project_state_assessments", null=True, blank=True)
    summary = models.TextField()
    known_assets = models.JSONField(default=list, blank=True)
    gaps = models.JSONField(default=list, blank=True)
    recommended_next_steps = models.JSONField(default=list, blank=True)
    evidence = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.CURRENT)
    created_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)


class ObjectiveRisk(models.Model):
    class Category(models.TextChoices):
        TECHNICAL = "TECHNICAL"
        TIMELINE = "TIMELINE"
        RESOURCE = "RESOURCE"
        DEPENDENCY = "DEPENDENCY"
        SCOPE = "SCOPE"
        EXTERNAL = "EXTERNAL"

    class Severity(models.TextChoices):
        LOW = "LOW"
        MEDIUM = "MEDIUM"
        HIGH = "HIGH"
        CRITICAL = "CRITICAL"

    class Status(models.TextChoices):
        IDENTIFIED = "IDENTIFIED"
        MITIGATED = "MITIGATED"
        ACCEPTED = "ACCEPTED"
        ESCALATED = "ESCALATED"
        RESOLVED = "RESOLVED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    objective = models.ForeignKey(Objective, on_delete=models.CASCADE, related_name="risks")
    title = models.CharField(max_length=240)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=32, choices=Category.choices, default=Category.TECHNICAL)
    severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.MEDIUM)
    likelihood = models.CharField(max_length=16, choices=Severity.choices, default=Severity.MEDIUM)
    mitigation_plan = models.TextField(blank=True)
    contingency_plan = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.IDENTIFIED)
    owner = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self) -> None:
        if not self.title or not self.title.strip():
            raise ValidationError({"title": "Risk title cannot be empty."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.title = self.title.strip()
        super().save(*args, **kwargs)

