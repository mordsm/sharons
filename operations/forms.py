import uuid

from django import forms

from operations.models import Evidence, Task


class DashboardActionForm(forms.Form):
    idempotency_key = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.initial.get("idempotency_key"):
            self.initial["idempotency_key"] = f"dashboard-{uuid.uuid4()}"


class TaskTransitionForm(DashboardActionForm):
    to_status = forms.ChoiceField(choices=Task.Status.choices)
    expected_version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)


class TaskAssignForm(DashboardActionForm):
    agent_id = forms.CharField(max_length=128)
    expected_version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)


class TaskEvidenceForm(DashboardActionForm):
    kind = forms.ChoiceField(choices=Evidence.Kind.choices)
    uri_or_reference = forms.CharField()
    checksum = forms.CharField(required=False, max_length=128)
    verified = forms.BooleanField(required=False)


class TaskVerifyForm(DashboardActionForm):
    mark_passed = forms.BooleanField(required=False)
    notes = forms.CharField(required=False, widget=forms.Textarea)
