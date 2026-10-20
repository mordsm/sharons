from django.db import models
import uuid


class IdempotencyRecord(models.Model):
    key = models.CharField(max_length=128, unique=True)
    request_hash = models.CharField(max_length=64)
    response_payload = models.JSONField()
    status_code = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class MemoryRecord(models.Model):
    class RecordType(models.TextChoices):
        DECISION = "DECISION"
        LESSON = "LESSON"
        STATUS_SUMMARY = "STATUS_SUMMARY"
        SOP = "SOP"
        FACT = "FACT"
        REFERENCE = "REFERENCE"

    class SourceType(models.TextChoices):
        HUMAN_ENTRY = "HUMAN_ENTRY"
        TASK = "TASK"
        APPROVAL = "APPROVAL"
        AUDIT_EVENT = "AUDIT_EVENT"
        CONVERSATION = "CONVERSATION"
        DOCUMENT = "DOCUMENT"

    class Classification(models.TextChoices):
        PUBLIC = "PUBLIC"
        INTERNAL = "INTERNAL"
        CONFIDENTIAL = "CONFIDENTIAL"
        PERSONAL_SENSITIVE = "PERSONAL_SENSITIVE"

    class VerificationStatus(models.TextChoices):
        UNVERIFIED = "UNVERIFIED"
        VERIFIED = "VERIFIED"
        SUPERSEDED = "SUPERSEDED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    record_type = models.CharField(max_length=32, choices=RecordType.choices)
    title = models.CharField(max_length=240)
    content = models.JSONField(default=dict)
    source_type = models.CharField(max_length=32, choices=SourceType.choices)
    source_id = models.CharField(max_length=128)
    owner = models.CharField(max_length=128)
    classification = models.CharField(max_length=32, choices=Classification.choices, default=Classification.INTERNAL)
    verification_status = models.CharField(max_length=32, choices=VerificationStatus.choices, default=VerificationStatus.UNVERIFIED)
    version = models.PositiveIntegerField(default=1)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    supersedes = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="superseded_by")
    embedding_reference = models.CharField(max_length=256, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        if not self.title or not self.title.strip():
            raise ValidationError({"title": "Memory title cannot be empty."})
        if not isinstance(self.content, dict):
            raise ValidationError({"content": "Memory content must be an object."})
        if not self.source_id or not self.source_id.strip():
            raise ValidationError({"source_id": "Source ID cannot be empty."})
        if not self.owner or not self.owner.strip():
            raise ValidationError({"owner": "Owner cannot be empty."})
        if (
            self.source_type == self.SourceType.CONVERSATION
            and self.record_type == self.RecordType.DECISION
            and self.verification_status == self.VerificationStatus.VERIFIED
        ):
            raise ValidationError({"verification_status": "Conversation summaries cannot become verified decisions automatically."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.title = self.title.strip()
        self.source_id = self.source_id.strip()
        self.owner = self.owner.strip()
        self.embedding_reference = self.embedding_reference.strip()
        super().save(*args, **kwargs)
