import pytest

from governance.models import ApprovalRequest, AuditEvent, RuleEngineRun, RuleEngineWorkItem
from governance.services import create_approval_request
from django.utils import timezone


pytestmark = pytest.mark.django_db


@pytest.fixture
def rule_engine_run():
    run = RuleEngineRun.objects.create(
        source="gmail_mock",
        external_event_id="msg-1",
        event_type="inbound_email.route",
        event_payload={"event_type": "inbound_email.route"},
        dry_run=True,
        final_decision="require_approval",
        risk_level="high",
        reason_codes=["SENSITIVE_EMAIL_REQUIRES_HUMAN_REVIEW"],
        matched_rules=[{"rule_id": "email_sensitive_or_commitment_requires_approval"}],
        approval_required_actions=[{"action_type": "review_sensitive_email"}],
        raw_result={"final_decision": "require_approval"},
    )
    create_approval_request(
        subject_type="governance.RuleEngineRun",
        subject_id=str(run.id),
        subject_version=1,
        action="governance.rules_engine.review",
        action_payload={"rule_engine_run_id": str(run.id), "dry_run": True},
        requested_by="chief_of_staff",
        correlation_id="corr-runs-test",
        expires_at=timezone.now() + timezone.timedelta(hours=24),
        reason_codes=run.reason_codes,
    )
    return run


def test_rules_engine_runs_list_returns_runs_with_approval_link(client, rule_engine_run):
    response = client.get("/api/v1/rules-engine/runs/")

    assert response.status_code == 200
    body = response.json()
    assert len(body["runs"]) == 1
    assert body["runs"][0]["id"] == str(rule_engine_run.id)
    assert body["runs"][0]["approval_status"] == ApprovalRequest.Status.PENDING


def test_rules_engine_runs_list_filters(client, rule_engine_run):
    response = client.get("/api/v1/rules-engine/runs/", {"source": "other"})

    assert response.status_code == 200
    assert response.json()["runs"] == []


def test_rules_engine_run_detail_includes_raw_result(client, rule_engine_run):
    response = client.get(f"/api/v1/rules-engine/runs/{rule_engine_run.id}/")

    assert response.status_code == 200
    body = response.json()["run"]
    assert body["raw_result"]["final_decision"] == "require_approval"
    assert body["matched_rules"][0]["rule_id"] == "email_sensitive_or_commitment_requires_approval"


def test_rules_engine_dashboard_requires_login(client):
    response = client.get("/rules-engine/")

    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


def test_rules_engine_dashboard_renders_runs(client, django_user_model, rule_engine_run):
    RuleEngineWorkItem.objects.create(
        run=rule_engine_run,
        item_type="APPROVAL_REQUIRED_ACTION",
        action_type="review_sensitive_email",
        title="Review sensitive email",
        component="owner_review",
        purpose="review_sensitive_email",
    )
    user = django_user_model.objects.create_user(username="ops", password="secret")
    client.force_login(user)

    response = client.get("/rules-engine/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "Rule Engine Runs" in content
    assert "Work Queue" in content
    assert "inbound_email.route" in content
    assert "Review sensitive email" in content
    assert "SENSITIVE_EMAIL_REQUIRES_HUMAN_REVIEW" in content


def test_rules_engine_dashboard_updates_work_item(client, django_user_model, rule_engine_run):
    item = RuleEngineWorkItem.objects.create(
        run=rule_engine_run,
        item_type="APPROVAL_REQUIRED_ACTION",
        action_type="review_sensitive_email",
        title="Review sensitive email",
        component="owner_review",
        purpose="review_sensitive_email",
    )
    user = django_user_model.objects.create_user(username="ops", password="secret")
    client.force_login(user)

    response = client.post(
        "/rules-engine/",
        data={"item_id": str(item.id), "owner_agent_id": "executive_assistant", "status": ""},
    )

    assert response.status_code == 302
    item.refresh_from_db()
    assert item.status == RuleEngineWorkItem.Status.ASSIGNED
    assert item.owner_agent_id == "executive_assistant"
    assert AuditEvent.objects.filter(action="governance.rules_engine.work_item.updated", object_id=str(item.id)).exists()
