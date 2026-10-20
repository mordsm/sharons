import uuid

from django.core.exceptions import ValidationError
from django.db import models

from portfolio.models import Objective


class Plan(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        PENDING_APPROVAL = "PENDING_APPROVAL"
        ACTIVE = "ACTIVE"
        CLOSED = "CLOSED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    objective = models.ForeignKey(Objective, on_delete=models.PROTECT, related_name="plans")
    name = models.CharField(max_length=200)
    version = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.DRAFT)
    assumptions = models.JSONField(default=dict, blank=True)
    risks = models.JSONField(default=dict, blank=True)
    created_by = models.CharField(max_length=128)
    approved_by = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self) -> None:
        if not self.name or not self.name.strip():
            raise ValidationError({"name": "Plan name cannot be empty."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.name = self.name.strip()
        super().save(*args, **kwargs)


class Task(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        PLANNED = "PLANNED"
        PENDING_APPROVAL = "PENDING_APPROVAL"
        APPROVED = "APPROVED"
        ASSIGNED = "ASSIGNED"
        IN_PROGRESS = "IN_PROGRESS"
        BLOCKED = "BLOCKED"
        DELIVERED_UNVERIFIED = "DELIVERED_UNVERIFIED"
        VERIFYING = "VERIFYING"
        COMPLETED = "COMPLETED"
        FAILED = "FAILED"
        CANCELLED = "CANCELLED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    objective = models.ForeignKey(Objective, on_delete=models.PROTECT, related_name="tasks")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="tasks", null=True, blank=True)
    external_key = models.CharField(max_length=128, blank=True)
    title = models.CharField(max_length=240)
    business_outcome = models.TextField(blank=True)
    owner_agent_id = models.CharField(max_length=128, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.DRAFT)
    created_by = models.CharField(max_length=128)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self) -> None:
        if not self.title or not self.title.strip():
            raise ValidationError({"title": "Task title cannot be empty."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.title = self.title.strip()
        super().save(*args, **kwargs)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["objective", "external_key"],
                condition=~models.Q(external_key=""),
                name="unique_task_external_key_per_objective",
            )
        ]


class AcceptanceCriterion(models.Model):
    class CriterionType(models.TextChoices):
        MANUAL = "MANUAL"
        AUTOMATED = "AUTOMATED"
        EVIDENCE = "EVIDENCE"

    class Status(models.TextChoices):
        PENDING = "PENDING"
        PASSED = "PASSED"
        FAILED = "FAILED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="acceptance_criteria")
    description = models.TextField()
    criterion_type = models.CharField(max_length=16, choices=CriterionType.choices, default=CriterionType.MANUAL)
    required = models.BooleanField(default=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    verified_by = models.CharField(max_length=128, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    def clean(self) -> None:
        if not self.description or not self.description.strip():
            raise ValidationError({"description": "Acceptance criterion cannot be empty."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.description = self.description.strip()
        super().save(*args, **kwargs)


class Evidence(models.Model):
    class Kind(models.TextChoices):
        TEST = "TEST"
        SOURCE = "SOURCE"
        ARTIFACT = "ARTIFACT"
        HUMAN_CONFIRMATION = "HUMAN_CONFIRMATION"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="evidence")
    kind = models.CharField(max_length=32, choices=Kind.choices)
    uri_or_reference = models.TextField()
    checksum = models.CharField(max_length=128, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    verified = models.BooleanField(default=False)
    created_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self) -> None:
        if not self.uri_or_reference or not self.uri_or_reference.strip():
            raise ValidationError({"uri_or_reference": "Evidence reference cannot be empty."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.uri_or_reference = self.uri_or_reference.strip()
        self.checksum = self.checksum.strip()
        self.created_by = self.created_by.strip() or "api"
        super().save(*args, **kwargs)


class AgentDefinition(models.Model):
    class RiskLevel(models.IntegerChoices):
        LOW = 1
        MEDIUM = 2
        HIGH = 3

    agent_id = models.CharField(max_length=128, unique=True)
    role = models.CharField(max_length=128)
    capabilities = models.JSONField(default=list, blank=True)
    tools = models.JSONField(default=list, blank=True)
    allowed_data_classes = models.JSONField(default=list, blank=True)
    forbidden_actions = models.JSONField(default=list, blank=True)
    max_risk_level = models.PositiveSmallIntegerField(choices=RiskLevel.choices, default=RiskLevel.LOW)
    max_concurrent_tasks = models.PositiveSmallIntegerField(default=1)
    current_task_count = models.PositiveSmallIntegerField(default=0)
    reliability_score = models.DecimalField(max_digits=4, decimal_places=2, default=1.0)
    prompt_version = models.CharField(max_length=64, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self) -> None:
        if not self.agent_id or not self.agent_id.strip():
            raise ValidationError({"agent_id": "Agent ID cannot be empty."})
        if not self.role or not self.role.strip():
            raise ValidationError({"role": "Agent role cannot be empty."})
        if not isinstance(self.capabilities, list):
            raise ValidationError({"capabilities": "Capabilities must be a list."})
        if not isinstance(self.tools, list):
            raise ValidationError({"tools": "Tools must be a list."})
        if not isinstance(self.allowed_data_classes, list):
            raise ValidationError({"allowed_data_classes": "Allowed data classes must be a list."})
        if not isinstance(self.forbidden_actions, list):
            raise ValidationError({"forbidden_actions": "Forbidden actions must be a list."})
        if self.current_task_count > self.max_concurrent_tasks:
            raise ValidationError({"current_task_count": "Current task count cannot exceed max concurrent tasks."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.agent_id = self.agent_id.strip()
        self.role = self.role.strip()
        self.prompt_version = self.prompt_version.strip()
        super().save(*args, **kwargs)


class AgentRun(models.Model):
    class Status(models.TextChoices):
        STARTED = "STARTED"
        COMPLETED = "COMPLETED"
        FAILED = "FAILED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="agent_runs")
    agent_id = models.CharField(max_length=128)
    attempt_number = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.STARTED)
    input_snapshot = models.JSONField(default=dict, blank=True)
    output = models.JSONField(default=dict, blank=True)
    token_or_cost_metadata = models.JSONField(default=dict, blank=True)
    correlation_id = models.CharField(max_length=128)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def clean(self) -> None:
        if not self.agent_id or not self.agent_id.strip():
            raise ValidationError({"agent_id": "Agent ID cannot be empty."})
        if not isinstance(self.input_snapshot, dict):
            raise ValidationError({"input_snapshot": "Input snapshot must be an object."})
        if not isinstance(self.output, dict):
            raise ValidationError({"output": "Output must be an object."})
        if not isinstance(self.token_or_cost_metadata, dict):
            raise ValidationError({"token_or_cost_metadata": "Token or cost metadata must be an object."})
        if self.attempt_number < 1:
            raise ValidationError({"attempt_number": "Attempt number must be positive."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.agent_id = self.agent_id.strip()
        self.correlation_id = self.correlation_id.strip()
        super().save(*args, **kwargs)


class TaskDependency(models.Model):
    class DependencyType(models.TextChoices):
        BLOCKS = "BLOCKS"
        RELATES_TO = "RELATES_TO"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="dependencies")
    depends_on = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="dependents")
    dependency_type = models.CharField(max_length=16, choices=DependencyType.choices, default=DependencyType.BLOCKS)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["task", "depends_on"], name="unique_task_dependency"),
            models.CheckConstraint(condition=~models.Q(task=models.F("depends_on")), name="prevent_self_dependency"),
        ]

    def clean(self) -> None:
        if self.task_id and self.depends_on_id and self.task_id == self.depends_on_id:
            raise ValidationError({"depends_on": "A task cannot depend on itself."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

