import json

from django import forms

from governance.models import ApprovalRequest


class ApprovalDecisionForm(forms.Form):
    decision = forms.ChoiceField(
        choices=[
            (ApprovalRequest.Status.APPROVED, "Approve"),
            (ApprovalRequest.Status.REJECTED, "Reject"),
        ],
        widget=forms.RadioSelect,
    )
    subject_version = forms.IntegerField(min_value=1)
    action_payload = forms.CharField(widget=forms.Textarea)

    def clean_action_payload(self):
        raw_payload = self.cleaned_data["action_payload"]
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError("Action payload must be valid JSON.") from exc
        if not isinstance(payload, dict):
            raise forms.ValidationError("Action payload must be a JSON object.")
        return payload


def approval_decision_initial(approval: ApprovalRequest) -> dict:
    return {
        "decision": ApprovalRequest.Status.APPROVED,
        "subject_version": approval.subject_version,
        "action_payload": json.dumps(approval.action_payload, sort_keys=True),
    }
