import uuid

from django.db import models


class AuditEvent(models.Model):
    class ActorType(models.TextChoices):
        HUMAN = "HUMAN"
        SYSTEM = "SYSTEM"
        AGENT = "AGENT"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    occurred_at = models.DateTimeField(auto_now_add=True)
    actor_type = models.CharField(max_length=16, choices=ActorType.choices)
    actor_id = models.CharField(max_length=128)
    action = models.CharField(max_length=128)
    object_type = models.CharField(max_length=128)
    object_id = models.CharField(max_length=128)
    before_hash = models.CharField(max_length=64, blank=True)
    after_hash = models.CharField(max_length=64, blank=True)
    correlation_id = models.CharField(max_length=128)
    causation_id = models.CharField(max_length=128, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-occurred_at"]


class Rule(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        VALIDATED = "VALIDATED"
        TESTED = "TESTED"
        PENDING_APPROVAL = "PENDING_APPROVAL"
        ACTIVE = "ACTIVE"
        SUSPENDED = "SUSPENDED"
        RETIRED = "RETIRED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rule_id = models.CharField(max_length=128)
    version = models.PositiveIntegerField()
    name = models.CharField(max_length=200)
    owner = models.CharField(max_length=128)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.DRAFT)
    trigger = models.JSONField(default=dict)
    conditions = models.JSONField(default=dict)
    decision = models.CharField(max_length=32)
    reason_codes = models.JSONField(default=list, blank=True)
    schema_version = models.PositiveIntegerField(default=1)
    approved_by = models.CharField(max_length=128, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    valid_from = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["rule_id", "version"], name="unique_rule_version"),
            models.UniqueConstraint(
                fields=["rule_id"],
                condition=models.Q(status="ACTIVE"),
                name="unique_active_rule_per_rule_id",
            ),
        ]


class RuleEvaluation(models.Model):
    class Decision(models.TextChoices):
        ALLOW = "ALLOW"
        ALLOW_AND_NOTIFY = "ALLOW_AND_NOTIFY"
        REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
        BLOCK = "BLOCK"
        NEEDS_MORE_DATA = "NEEDS_MORE_DATA"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_id = models.CharField(max_length=128)
    rule = models.ForeignKey(Rule, on_delete=models.PROTECT, related_name="evaluations", null=True, blank=True)
    decision = models.CharField(max_length=32, choices=Decision.choices)
    matched_paths = models.JSONField(default=list, blank=True)
    reason_codes = models.JSONField(default=list, blank=True)
    input_snapshot_hash = models.CharField(max_length=64)
    evaluated_at = models.DateTimeField(auto_now_add=True)


class RuleEngineRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.CharField(max_length=128)
    external_event_id = models.CharField(max_length=200)
    event_type = models.CharField(max_length=128)
    event_payload = models.JSONField(default=dict)
    dry_run = models.BooleanField(default=True)
    final_decision = models.CharField(max_length=64)
    risk_level = models.CharField(max_length=32)
    reason_codes = models.JSONField(default=list, blank=True)
    matched_rules = models.JSONField(default=list, blank=True)
    allowed_actions = models.JSONField(default=list, blank=True)
    approval_required_actions = models.JSONField(default=list, blank=True)
    blocked_actions = models.JSONField(default=list, blank=True)
    routes = models.JSONField(default=list, blank=True)
    raw_result = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["source", "external_event_id"], name="unique_rule_engine_run_source_external_id"),
        ]


class RuleEngineWorkItem(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN"
        ASSIGNED = "ASSIGNED"
        COMPLETED = "COMPLETED"
        CANCELLED = "CANCELLED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(RuleEngineRun, on_delete=models.PROTECT, related_name="work_items")
    execution = models.ForeignKey("ApprovedActionExecution", on_delete=models.PROTECT, related_name="rule_engine_work_items", null=True, blank=True)
    item_type = models.CharField(max_length=64)
    action_type = models.CharField(max_length=128, blank=True)
    title = models.CharField(max_length=240, blank=True)
    component = models.CharField(max_length=128, blank=True)
    purpose = models.CharField(max_length=240, blank=True)
    reason_code = models.CharField(max_length=128, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.OPEN)
    owner_agent_id = models.CharField(max_length=128, blank=True)
    no_external_action = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class RuleTestCase(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rule = models.ForeignKey(Rule, on_delete=models.CASCADE, related_name="test_cases")
    name = models.CharField(max_length=200)
    input_event = models.JSONField(default=dict)
    expected_decision = models.CharField(max_length=32, choices=RuleEvaluation.Decision.choices)
    expected_match = models.BooleanField(default=True)
    passed = models.BooleanField(default=False)
    actual_decision = models.CharField(max_length=32, blank=True)
    matched_paths = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        if not self.name or not self.name.strip():
            raise ValidationError({"name": "Rule test name cannot be empty."})
        if not isinstance(self.input_event, dict):
            raise ValidationError({"input_event": "Rule test input_event must be an object."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.name = self.name.strip()
        super().save(*args, **kwargs)


class ApprovalRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING"
        APPROVED = "APPROVED"
        REJECTED = "REJECTED"
        EXPIRED = "EXPIRED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject_type = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=128)
    subject_version = models.PositiveIntegerField()
    action = models.CharField(max_length=128)
    action_payload = models.JSONField(default=dict)
    action_payload_hash = models.CharField(max_length=64)
    requested_by = models.CharField(max_length=128)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    reason_codes = models.JSONField(default=list, blank=True)
    expires_at = models.DateTimeField()
    decided_by = models.CharField(max_length=128, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        permissions = [
            ("decide_approvalrequest", "Can decide approval requests"),
        ]


class ApprovedActionExecution(models.Model):
    class Status(models.TextChoices):
        SUCCEEDED = "SUCCEEDED"
        FAILED = "FAILED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    approval = models.OneToOneField(ApprovalRequest, on_delete=models.PROTECT, related_name="execution")
    action = models.CharField(max_length=128)
    status = models.CharField(max_length=16, choices=Status.choices)
    result = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.TextField(blank=True)
    executed_by = models.CharField(max_length=128)
    correlation_id = models.CharField(max_length=128)
    executed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-executed_at"]


class OutboxMessage(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING"
        SENT = "SENT"
        FAILED = "FAILED"
        DEAD_LETTER = "DEAD_LETTER"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    topic = models.CharField(max_length=128)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=200, unique=True)
    correlation_id = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        if not self.topic or not self.topic.strip():
            raise ValidationError({"topic": "Outbox topic cannot be empty."})
        if not isinstance(self.payload, dict):
            raise ValidationError({"payload": "Outbox payload must be an object."})
        if not self.idempotency_key or not self.idempotency_key.strip():
            raise ValidationError({"idempotency_key": "Outbox idempotency key cannot be empty."})
        if not self.correlation_id or not self.correlation_id.strip():
            raise ValidationError({"correlation_id": "Correlation ID cannot be empty."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.topic = self.topic.strip()
        self.idempotency_key = self.idempotency_key.strip()
        self.correlation_id = self.correlation_id.strip()
        super().save(*args, **kwargs)


class InboxEvent(models.Model):
    class Status(models.TextChoices):
        RECEIVED = "RECEIVED"
        PROCESSED = "PROCESSED"
        FAILED = "FAILED"
        IGNORED = "IGNORED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.CharField(max_length=128)
    external_event_id = models.CharField(max_length=200)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RECEIVED)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    correlation_id = models.CharField(max_length=128)

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        if not self.source or not self.source.strip():
            raise ValidationError({"source": "Inbox source cannot be empty."})
        if not self.external_event_id or not self.external_event_id.strip():
            raise ValidationError({"external_event_id": "External event ID cannot be empty."})
        if not isinstance(self.payload, dict):
            raise ValidationError({"payload": "Inbox payload must be an object."})
        if not self.correlation_id or not self.correlation_id.strip():
            raise ValidationError({"correlation_id": "Correlation ID cannot be empty."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.source = self.source.strip()
        self.external_event_id = self.external_event_id.strip()
        self.correlation_id = self.correlation_id.strip()
        super().save(*args, **kwargs)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source", "external_event_id"], name="unique_inbox_event_source_external_id"),
        ]
