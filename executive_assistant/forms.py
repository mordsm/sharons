import uuid

from django import forms

from executive_assistant.models import ExecutiveBrief, ExecutiveBriefTaskProposal, ExecutiveEmailDraft, ExecutiveProviderSyncConfig
from portfolio.models import Objective


class ExecutiveBriefCreateForm(forms.Form):
    idempotency_key = forms.CharField(widget=forms.HiddenInput, initial=lambda: f"ea-brief-ui-{uuid.uuid4()}")
    brief_type = forms.ChoiceField(choices=ExecutiveBrief.BriefType.choices)
    title = forms.CharField(max_length=200)
    source_window_days = forms.IntegerField(min_value=1, max_value=90, required=False)


class ExecutiveBriefTaskProposalForm(forms.Form):
    idempotency_key = forms.CharField(widget=forms.HiddenInput, initial=lambda: f"ea-task-propose-ui-{uuid.uuid4()}")
    objective_id = forms.ModelChoiceField(queryset=Objective.objects.none(), empty_label=None)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["objective_id"].queryset = Objective.objects.filter(status=Objective.Status.ACTIVE).order_by("code")


class ExecutiveBriefArchiveForm(forms.Form):
    idempotency_key = forms.CharField(widget=forms.HiddenInput, initial=lambda: f"ea-brief-archive-ui-{uuid.uuid4()}")


class ExecutiveTaskProposalReviewForm(forms.Form):
    idempotency_key = forms.CharField(widget=forms.HiddenInput, initial=lambda: f"ea-task-review-ui-{uuid.uuid4()}")
    decision = forms.ChoiceField(
        choices=[
            (ExecutiveBriefTaskProposal.ReviewStatus.ACCEPTED, "Accept"),
            (ExecutiveBriefTaskProposal.ReviewStatus.DISMISSED, "Dismiss"),
        ]
    )
    review_note = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)


class ExecutiveEmailDraftReviewForm(forms.Form):
    idempotency_key = forms.CharField(widget=forms.HiddenInput, initial=lambda: f"ea-email-review-ui-{uuid.uuid4()}")
    decision = forms.ChoiceField(
        choices=[
            (ExecutiveEmailDraft.ReviewStatus.APPROVED, "Approve"),
            (ExecutiveEmailDraft.ReviewStatus.REJECTED, "Reject"),
        ]
    )
    review_note = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)


class ExecutiveEmailDraftApprovalRequestForm(forms.Form):
    idempotency_key = forms.CharField(widget=forms.HiddenInput, initial=lambda: f"ea-email-approval-ui-{uuid.uuid4()}")
    expires_in_hours = forms.IntegerField(min_value=1, max_value=168, initial=24)


class ExecutiveReadOnlyEmailIngestForm(forms.Form):
    idempotency_key = forms.CharField(widget=forms.HiddenInput, initial=lambda: f"ea-email-ingest-ui-{uuid.uuid4()}")
    source = forms.CharField(max_length=128, initial="email_readonly")
    external_event_id = forms.CharField(max_length=200)
    sender = forms.EmailField()
    subject = forms.CharField(max_length=240)
    body = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}), required=False)


class ExecutiveReadOnlyCalendarIngestForm(forms.Form):
    idempotency_key = forms.CharField(widget=forms.HiddenInput, initial=lambda: f"ea-calendar-ingest-ui-{uuid.uuid4()}")
    source = forms.CharField(max_length=128, initial="calendar_readonly")
    external_event_id = forms.CharField(max_length=200)
    title = forms.CharField(max_length=240)
    starts_at = forms.DateTimeField()
    ends_at = forms.DateTimeField()
    organizer = forms.EmailField(required=False)
    attendees = forms.CharField(required=False, help_text="Comma-separated email addresses")
    location = forms.CharField(max_length=240, required=False)
    description = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)


class ExecutiveProviderSyncConfigForm(forms.Form):
    idempotency_key = forms.CharField(widget=forms.HiddenInput, initial=lambda: f"ea-provider-sync-ui-{uuid.uuid4()}")
    provider_type = forms.ChoiceField(choices=ExecutiveProviderSyncConfig.ProviderType.choices)
    provider_name = forms.CharField(max_length=80, initial="gmail")
    source = forms.CharField(max_length=128, initial="gmail_readonly")
    status = forms.ChoiceField(choices=ExecutiveProviderSyncConfig.Status.choices, initial=ExecutiveProviderSyncConfig.Status.PLANNED)
    scopes = forms.CharField(required=False, help_text="Comma-separated read-only scopes or labels")
