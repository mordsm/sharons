import uuid

from django.core.exceptions import ValidationError
from django.db import models

from operations.models import Task


class ExecutiveBrief(models.Model):
    class BriefType(models.TextChoices):
        WEEKLY_REVIEW_PREP = "WEEKLY_REVIEW_PREP"
        FOLLOW_UPS = "FOLLOW_UPS"
        INBOX_TRIAGE = "INBOX_TRIAGE"
        MORNING_BRIEF = "MORNING_BRIEF"

    class Status(models.TextChoices):
        READY = "READY"
        ARCHIVED = "ARCHIVED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brief_type = models.CharField(max_length=32, choices=BriefType.choices, default=BriefType.WEEKLY_REVIEW_PREP)
    title = models.CharField(max_length=200)
    source_window = models.JSONField(default=dict, blank=True)
    summary = models.TextField()
    agenda_items = models.JSONField(default=list, blank=True)
    follow_ups = models.JSONField(default=list, blank=True)
    decisions_needed = models.JSONField(default=list, blank=True)
    inbox_items = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.READY)
    no_external_send = models.BooleanField(default=True)
    created_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self) -> None:
        if not self.title or not self.title.strip():
            raise ValidationError({"title": "Title cannot be empty."})
        if not self.summary or not self.summary.strip():
            raise ValidationError({"summary": "Summary cannot be empty."})
        if not isinstance(self.source_window, dict):
            raise ValidationError({"source_window": "Source window must be an object."})
        if not isinstance(self.agenda_items, list):
            raise ValidationError({"agenda_items": "Agenda items must be a list."})
        if not isinstance(self.follow_ups, list):
            raise ValidationError({"follow_ups": "Follow-ups must be a list."})
        if not isinstance(self.decisions_needed, list):
            raise ValidationError({"decisions_needed": "Decisions needed must be a list."})
        if not isinstance(self.inbox_items, list):
            raise ValidationError({"inbox_items": "Inbox items must be a list."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.title = self.title.strip()
        self.summary = self.summary.strip()
        self.created_by = self.created_by.strip() or "api"
        super().save(*args, **kwargs)


class ExecutiveBriefTaskProposal(models.Model):
    class ReviewStatus(models.TextChoices):
        PENDING = "PENDING"
        ACCEPTED = "ACCEPTED"
        DISMISSED = "DISMISSED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brief = models.ForeignKey(ExecutiveBrief, on_delete=models.PROTECT, related_name="task_proposals")
    task_id = models.UUIDField()
    follow_up_index = models.PositiveSmallIntegerField()
    external_key = models.CharField(max_length=200)
    title = models.CharField(max_length=240)
    status = models.CharField(max_length=32)
    review_status = models.CharField(max_length=16, choices=ReviewStatus.choices, default=ReviewStatus.PENDING)
    reviewed_by = models.CharField(max_length=128, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    no_external_send = models.BooleanField(default=True)
    created_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["brief", "follow_up_index"], name="unique_task_proposal_per_brief_follow_up"),
        ]

    def clean(self) -> None:
        if not self.external_key or not self.external_key.strip():
            raise ValidationError({"external_key": "External key cannot be empty."})
        if not self.title or not self.title.strip():
            raise ValidationError({"title": "Title cannot be empty."})
        if not self.status or not self.status.strip():
            raise ValidationError({"status": "Status cannot be empty."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.external_key = self.external_key.strip()
        self.title = self.title.strip()
        self.status = self.status.strip()
        self.created_by = self.created_by.strip() or "api"
        super().save(*args, **kwargs)


class ExecutiveEmailDraft(models.Model):
    class DraftType(models.TextChoices):
        REPLY = "REPLY"
        FORWARD = "FORWARD"
        NEW_MESSAGE = "NEW_MESSAGE"

    class ReviewStatus(models.TextChoices):
        NEEDS_REVIEW = "NEEDS_REVIEW"
        APPROVED = "APPROVED"
        REJECTED = "REJECTED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_message_id = models.UUIDField(null=True, blank=True)
    draft_type = models.CharField(max_length=24, choices=DraftType.choices, default=DraftType.REPLY)
    to_recipients = models.JSONField(default=list)
    cc_recipients = models.JSONField(default=list, blank=True)
    subject = models.CharField(max_length=240)
    body = models.TextField()
    rationale = models.TextField(blank=True)
    review_status = models.CharField(max_length=24, choices=ReviewStatus.choices, default=ReviewStatus.NEEDS_REVIEW)
    reviewed_by = models.CharField(max_length=128, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    no_external_send = models.BooleanField(default=True)
    created_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self) -> None:
        if self.draft_type not in self.DraftType.values:
            raise ValidationError({"draft_type": "Draft type must be valid."})
        if not isinstance(self.to_recipients, list):
            raise ValidationError({"to_recipients": "To recipients must be a list."})
        if not isinstance(self.cc_recipients, list):
            raise ValidationError({"cc_recipients": "CC recipients must be a list."})
        if not self.to_recipients:
            raise ValidationError({"to_recipients": "At least one recipient is required."})
        if not self.subject or not self.subject.strip():
            raise ValidationError({"subject": "Subject cannot be empty."})
        if not self.body or not self.body.strip():
            raise ValidationError({"body": "Body cannot be empty."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.subject = self.subject.strip()
        self.body = self.body.strip()
        self.rationale = self.rationale.strip()
        self.created_by = self.created_by.strip() or "api"
        super().save(*args, **kwargs)


class ExecutiveCalendarEvent(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = "CONFIRMED"
        TENTATIVE = "TENTATIVE"
        CANCELLED = "CANCELLED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.CharField(max_length=128, default="calendar_readonly")
    external_event_id = models.CharField(max_length=200)
    title = models.CharField(max_length=240)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    organizer = models.EmailField(blank=True)
    attendees = models.JSONField(default=list, blank=True)
    location = models.CharField(max_length=240, blank=True)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.CONFIRMED)
    no_external_schedule = models.BooleanField(default=True)
    created_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["starts_at", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["source", "external_event_id"], name="unique_ea_calendar_source_external_id"),
        ]

    def clean(self) -> None:
        if not self.source or not self.source.strip():
            raise ValidationError({"source": "Source cannot be empty."})
        if not self.external_event_id or not self.external_event_id.strip():
            raise ValidationError({"external_event_id": "External event ID cannot be empty."})
        if not self.title or not self.title.strip():
            raise ValidationError({"title": "Title cannot be empty."})
        if self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "End time must be after start time."})
        if not isinstance(self.attendees, list):
            raise ValidationError({"attendees": "Attendees must be a list."})
        if self.status not in self.Status.values:
            raise ValidationError({"status": "Status must be valid."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.source = self.source.strip()
        self.external_event_id = self.external_event_id.strip()
        self.title = self.title.strip()
        self.location = self.location.strip()
        self.description = self.description.strip()
        self.created_by = self.created_by.strip() or "api"
        super().save(*args, **kwargs)


class ExecutiveProviderSyncConfig(models.Model):
    class ProviderType(models.TextChoices):
        EMAIL = "EMAIL"
        CALENDAR = "CALENDAR"

    class Status(models.TextChoices):
        PLANNED = "PLANNED"
        READY_FOR_CONNECTOR = "READY_FOR_CONNECTOR"
        PAUSED = "PAUSED"
        ERROR = "ERROR"

    class SyncMode(models.TextChoices):
        READ_ONLY = "READ_ONLY"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider_type = models.CharField(max_length=24, choices=ProviderType.choices)
    provider_name = models.CharField(max_length=80)
    source = models.CharField(max_length=128)
    sync_mode = models.CharField(max_length=24, choices=SyncMode.choices, default=SyncMode.READ_ONLY)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PLANNED)
    scopes = models.JSONField(default=list, blank=True)
    config = models.JSONField(default=dict, blank=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    no_external_action = models.BooleanField(default=True)
    created_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["provider_type", "provider_name", "source"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider_type", "provider_name", "source"],
                name="unique_ea_provider_sync_config",
            ),
        ]

    def clean(self) -> None:
        if self.provider_type not in self.ProviderType.values:
            raise ValidationError({"provider_type": "Provider type must be valid."})
        if not self.provider_name or not self.provider_name.strip():
            raise ValidationError({"provider_name": "Provider name cannot be empty."})
        if not self.source or not self.source.strip():
            raise ValidationError({"source": "Source cannot be empty."})
        source = self.source.strip().lower()
        if source.endswith("_send") or source.endswith("_write") or "smtp" in source or "schedule" in source:
            raise ValidationError({"source": "Source must identify a read-only provider feed."})
        if self.sync_mode != self.SyncMode.READ_ONLY:
            raise ValidationError({"sync_mode": "Only READ_ONLY sync mode is supported."})
        if self.status not in self.Status.values:
            raise ValidationError({"status": "Status must be valid."})
        if not isinstance(self.scopes, list):
            raise ValidationError({"scopes": "Scopes must be a list."})
        if not isinstance(self.config, dict):
            raise ValidationError({"config": "Config must be an object."})
        blocked_config_keys = {"access_token", "refresh_token", "client_secret", "password", "oauth_token"}
        if blocked_config_keys.intersection({str(key).lower() for key in self.config}):
            raise ValidationError({"config": "Provider config cannot store credentials or OAuth tokens."})
        if not self.no_external_action:
            raise ValidationError({"no_external_action": "Provider sync config cannot enable external actions."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.provider_name = self.provider_name.strip()
        self.source = self.source.strip()
        self.scopes = [str(item).strip() for item in self.scopes if str(item).strip()]
        self.created_by = self.created_by.strip() or "api"
        super().save(*args, **kwargs)


class DelegatedTaskFollowUp(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING"
        ON_TRACK = "ON_TRACK"
        AT_RISK = "AT_RISK"
        OVERDUE = "OVERDUE"
        COMPLETED = "COMPLETED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="delegation_follow_ups")
    delegated_to = models.CharField(max_length=128)
    delegated_by = models.CharField(max_length=128, default="ceo")
    title = models.CharField(max_length=240)
    due_at = models.DateTimeField()
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PENDING)
    nudge_count = models.PositiveIntegerField(default=0)
    last_nudged_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["due_at", "-created_at"]

    def clean(self) -> None:
        if not self.title or not self.title.strip():
            raise ValidationError({"title": "Title cannot be empty."})
        if not self.delegated_to or not self.delegated_to.strip():
            raise ValidationError({"delegated_to": "Delegated to cannot be empty."})
        if self.status not in self.Status.values:
            raise ValidationError({"status": "Status must be valid."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.title = self.title.strip()
        self.delegated_to = self.delegated_to.strip()
        self.delegated_by = self.delegated_by.strip() or "ceo"
        self.notes = self.notes.strip()
        super().save(*args, **kwargs)

