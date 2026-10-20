import json

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from executive_assistant.models import (
    ExecutiveBrief,
    ExecutiveBriefTaskProposal,
    ExecutiveCalendarEvent,
    ExecutiveEmailDraft,
    ExecutiveProviderSyncConfig,
)
from governance.models import ApprovalRequest, AuditEvent, RuleEngineRun, RuleEngineWorkItem
from governance.services import create_approval_request
from governance.models import RuleEvaluation
from mailbox.models import MockEmailMessage
from operations.models import Task
from portfolio.models import Objective, StrategyVersion


pytestmark = pytest.mark.django_db


def headers(key: str = "executive-brief-1") -> dict:
    return {"Idempotency-Key": key, "X-Correlation-ID": f"corr-{key}", "X-Actor-ID": "executive_assistant"}


@pytest.fixture
def active_objective():
    strategy = StrategyVersion.objects.create(version=1, title="90 day plan", content={}, status=StrategyVersion.Status.ACTIVE)
    return Objective.objects.create(
        code="O1",
        strategy_version=strategy,
        name="Mental Trainer commercial readiness",
        business_outcome="Prepare beta launch.",
        status=Objective.Status.ACTIVE,
    )


def test_executive_brief_create_summarizes_internal_state_and_audits(client, active_objective):
    task = Task.objects.create(
        objective=active_objective,
        title="Resolve onboarding blocker",
        status=Task.Status.BLOCKED,
        business_outcome="Beta path is unblocked.",
        created_by="chief",
    )
    create_approval_request(
        subject_type="operations.Task",
        subject_id=str(task.id),
        subject_version=task.version,
        action="operations.task.transition",
        action_payload={"to_status": Task.Status.APPROVED, "expected_version": task.version},
        requested_by="chief",
        correlation_id="corr-approval",
        expires_at=timezone.now() + timezone.timedelta(days=1),
    )
    MockEmailMessage.objects.create(
        source="mock_gmail",
        external_event_id="email-1",
        sender="ceo@example.local",
        subject="Decision needed on onboarding",
        body="Please decide.",
        classification=MockEmailMessage.Classification.DECISION,
        proposed_action={"type": "REQUEST_INTERNAL_DECISION"},
        rule_decision=RuleEvaluation.Decision.NEEDS_MORE_DATA,
    )

    response = client.post(
        "/api/v1/executive-assistant/briefs/create/",
        data=json.dumps({"title": "CEO weekly prep", "source_window": {"days": 7}}),
        content_type="application/json",
        headers=headers(),
    )

    assert response.status_code == 201
    body = response.json()["executive_brief"]
    assert body["brief_type"] == ExecutiveBrief.BriefType.WEEKLY_REVIEW_PREP
    assert body["no_external_send"] is True
    assert body["status"] == ExecutiveBrief.Status.READY
    assert body["follow_ups"][0]["task_id"] == str(task.id)
    assert body["decisions_needed"][0]["action"] == "operations.task.transition"
    assert body["inbox_items"][0]["classification"] == MockEmailMessage.Classification.DECISION
    assert ExecutiveBrief.objects.count() == 1
    assert AuditEvent.objects.filter(
        action="executive_assistant.brief.created",
        correlation_id="corr-executive-brief-1",
        metadata__no_external_send=True,
    ).exists()


def test_executive_brief_create_is_idempotent(client):
    payload = {"title": "Daily follow-ups", "brief_type": ExecutiveBrief.BriefType.FOLLOW_UPS}

    first = client.post("/api/v1/executive-assistant/briefs/create/", data=json.dumps(payload), content_type="application/json", headers=headers("executive-brief-2"))
    second = client.post("/api/v1/executive-assistant/briefs/create/", data=json.dumps(payload), content_type="application/json", headers=headers("executive-brief-2"))

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()
    assert ExecutiveBrief.objects.count() == 1


def test_executive_brief_create_rejects_reused_idempotency_key_with_different_payload(client):
    client.post(
        "/api/v1/executive-assistant/briefs/create/",
        data=json.dumps({"title": "Daily follow-ups"}),
        content_type="application/json",
        headers=headers("executive-brief-3"),
    )

    response = client.post(
        "/api/v1/executive-assistant/briefs/create/",
        data=json.dumps({"title": "Changed"}),
        content_type="application/json",
        headers=headers("executive-brief-3"),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert ExecutiveBrief.objects.count() == 1


def test_executive_assistant_status_is_read_only(client, active_objective):
    brief = ExecutiveBrief.objects.create(
        brief_type=ExecutiveBrief.BriefType.INBOX_TRIAGE,
        title="Inbox triage",
        summary="No external send.",
        follow_ups=[{"title": "Call back", "reason": "follow_up"}],
        created_by="executive_assistant",
    )
    ExecutiveBrief.objects.create(
        brief_type=ExecutiveBrief.BriefType.FOLLOW_UPS,
        title="Old follow-ups",
        summary="Archived.",
        status=ExecutiveBrief.Status.ARCHIVED,
        created_by="executive_assistant",
    )
    task = Task.objects.create(
        objective=active_objective,
        title="Follow up: Call back",
        status=Task.Status.DRAFT,
        owner_agent_id="executive_assistant",
        business_outcome="Follow-up resolved.",
        created_by="executive_assistant",
    )
    ExecutiveBriefTaskProposal.objects.create(
        brief=brief,
        task_id=task.id,
        follow_up_index=0,
        external_key=f"executive-brief:{brief.id}:follow-up:0",
        title=task.title,
        status=task.status,
        review_status=ExecutiveBriefTaskProposal.ReviewStatus.PENDING,
        created_by="executive_assistant",
    )

    response = client.get("/api/v1/executive-assistant/status/")

    assert response.status_code == 200
    status = response.json()["status"]
    assert status["agent_id"] == "executive_assistant"
    assert status["external_email_enabled"] is False
    assert status["external_calendar_enabled"] is False
    assert status["briefs"] == 2
    assert status["task_proposals"] == 1
    assert status["queue_counts"]["briefs"][ExecutiveBrief.Status.READY] == 1
    assert status["queue_counts"]["briefs"][ExecutiveBrief.Status.ARCHIVED] == 1
    assert status["queue_counts"]["ready_briefs_with_follow_ups"] == 1
    assert status["queue_counts"]["task_proposals"][ExecutiveBriefTaskProposal.ReviewStatus.PENDING] == 1
    assert status["queue_counts"]["task_proposals"][ExecutiveBriefTaskProposal.ReviewStatus.ACCEPTED] == 0
    assert status["queue_counts"]["email_drafts"][ExecutiveEmailDraft.ReviewStatus.NEEDS_REVIEW] == 0
    assert status["queue_counts"]["provider_sync_configs"][ExecutiveProviderSyncConfig.Status.READY_FOR_CONNECTOR] == 0
    assert status["queue_counts"]["rule_engine_work_items"][RuleEngineWorkItem.Status.ASSIGNED] == 0


def test_executive_assistant_operational_snapshot_is_read_only(client):
    ExecutiveProviderSyncConfig.objects.create(
        provider_type=ExecutiveProviderSyncConfig.ProviderType.EMAIL,
        provider_name="gmail",
        source="gmail_readonly",
        status=ExecutiveProviderSyncConfig.Status.READY_FOR_CONNECTOR,
        scopes=["gmail.readonly"],
        created_by="executive_assistant",
    )

    response = client.get("/api/v1/executive-assistant/operational-snapshot/")

    assert response.status_code == 200
    snapshot = response.json()["operational_snapshot"]
    assert snapshot["status"]["external_email_enabled"] is False
    assert snapshot["status"]["external_calendar_enabled"] is False
    assert snapshot["safety"]["external_actions_enabled"] is False
    assert snapshot["safety"]["email_send_allowed"] is False
    assert snapshot["safety"]["calendar_schedule_allowed"] is False
    assert snapshot["provider_connectors"]["real_provider_connections_enabled"] is False
    assert snapshot["provider_readiness_summary"]["ready"] == 1
    assert snapshot["provider_readiness_summary"]["external_action_enabled"] is False
    assert AuditEvent.objects.count() == 0


def test_executive_provider_sync_config_create_is_read_only_readiness_only(client):
    response = client.post(
        "/api/v1/executive-assistant/provider-sync-configs/create/",
        data=json.dumps(
            {
                "provider_type": ExecutiveProviderSyncConfig.ProviderType.EMAIL,
                "provider_name": "gmail",
                "source": "gmail_readonly",
                "status": ExecutiveProviderSyncConfig.Status.READY_FOR_CONNECTOR,
                "scopes": ["gmail.readonly"],
                "config": {"label": "primary"},
            }
        ),
        content_type="application/json",
        headers=headers("ea-provider-sync-1"),
    )

    assert response.status_code == 201
    body = response.json()["provider_sync_config"]
    assert body["provider_type"] == ExecutiveProviderSyncConfig.ProviderType.EMAIL
    assert body["provider_name"] == "gmail"
    assert body["source"] == "gmail_readonly"
    assert body["sync_mode"] == ExecutiveProviderSyncConfig.SyncMode.READ_ONLY
    assert body["status"] == ExecutiveProviderSyncConfig.Status.READY_FOR_CONNECTOR
    assert body["no_external_action"] is True
    assert ExecutiveProviderSyncConfig.objects.count() == 1
    assert AuditEvent.objects.filter(
        action="executive_assistant.provider_sync_config.upserted",
        correlation_id="corr-ea-provider-sync-1",
        metadata__no_external_action=True,
    ).exists()


def test_executive_provider_sync_config_rejects_send_capable_source_and_secrets(client):
    send_source_response = client.post(
        "/api/v1/executive-assistant/provider-sync-configs/create/",
        data=json.dumps(
            {
                "provider_type": ExecutiveProviderSyncConfig.ProviderType.EMAIL,
                "provider_name": "gmail",
                "source": "gmail_send",
                "config": {},
            }
        ),
        content_type="application/json",
        headers=headers("ea-provider-sync-2"),
    )
    secret_response = client.post(
        "/api/v1/executive-assistant/provider-sync-configs/create/",
        data=json.dumps(
            {
                "provider_type": ExecutiveProviderSyncConfig.ProviderType.CALENDAR,
                "provider_name": "google_calendar",
                "source": "google_calendar_readonly",
                "config": {"access_token": "never-store-this"},
            }
        ),
        content_type="application/json",
        headers=headers("ea-provider-sync-3"),
    )

    assert send_source_response.status_code == 400
    assert secret_response.status_code == 400
    assert ExecutiveProviderSyncConfig.objects.count() == 0


def test_executive_provider_sync_configs_list_filters_by_type(client):
    ExecutiveProviderSyncConfig.objects.create(
        provider_type=ExecutiveProviderSyncConfig.ProviderType.EMAIL,
        provider_name="gmail",
        source="gmail_readonly",
        status=ExecutiveProviderSyncConfig.Status.READY_FOR_CONNECTOR,
        created_by="executive_assistant",
    )
    ExecutiveProviderSyncConfig.objects.create(
        provider_type=ExecutiveProviderSyncConfig.ProviderType.CALENDAR,
        provider_name="google_calendar",
        source="google_calendar_readonly",
        created_by="executive_assistant",
    )

    response = client.get(
        "/api/v1/executive-assistant/provider-sync-configs/",
        {"provider_type": ExecutiveProviderSyncConfig.ProviderType.EMAIL},
    )

    assert response.status_code == 200
    configs = response.json()["provider_sync_configs"]
    assert len(configs) == 1
    assert configs[0]["provider_name"] == "gmail"


def test_executive_provider_connectors_status_lists_disabled_read_only_stubs(client):
    response = client.get("/api/v1/executive-assistant/provider-connectors/")

    assert response.status_code == 200
    status = response.json()["provider_connectors"]
    assert status["external_email_enabled"] is False
    assert status["external_calendar_enabled"] is False
    assert status["real_provider_connections_enabled"] is False
    connector_keys = {connector["connector_key"] for connector in status["connectors"]}
    assert {"gmail_readonly", "google_calendar_readonly", "outlook_email_readonly", "outlook_calendar_readonly"}.issubset(connector_keys)
    assert all(connector["adapter_available"] is False for connector in status["connectors"])
    assert all(connector["external_action_enabled"] is False for connector in status["connectors"])


def test_executive_provider_sync_config_readiness_reports_disabled_adapter(client):
    config = ExecutiveProviderSyncConfig.objects.create(
        provider_type=ExecutiveProviderSyncConfig.ProviderType.EMAIL,
        provider_name="gmail",
        source="gmail_readonly",
        status=ExecutiveProviderSyncConfig.Status.READY_FOR_CONNECTOR,
        scopes=["gmail.readonly"],
        created_by="executive_assistant",
    )

    response = client.get(f"/api/v1/executive-assistant/provider-sync-configs/{config.id}/readiness/")

    assert response.status_code == 200
    readiness = response.json()["readiness"]
    assert readiness["ready"] is True
    assert readiness["external_action_enabled"] is False
    assert readiness["adapter_available"] is False
    assert readiness["oauth_configured"] is False
    assert readiness["dry_run_only"] is True
    assert readiness["connector"]["connector_key"] == "gmail_readonly"
    assert readiness["blockers"] == []


def test_executive_provider_sync_config_plan_is_read_only_and_side_effect_free(client):
    config = ExecutiveProviderSyncConfig.objects.create(
        provider_type=ExecutiveProviderSyncConfig.ProviderType.EMAIL,
        provider_name="outlook_email",
        source="outlook_email_readonly",
        status=ExecutiveProviderSyncConfig.Status.READY_FOR_CONNECTOR,
        scopes=["mail.read"],
        created_by="executive_assistant",
    )

    response = client.get(f"/api/v1/executive-assistant/provider-sync-configs/{config.id}/sync-plan/")

    assert response.status_code == 200
    body = response.json()
    plan = body["sync_plan"]
    assert body["readiness"]["ready"] is True
    assert plan["connector"]["connector_key"] == "outlook_email_readonly"
    assert plan["sync_mode"] == ExecutiveProviderSyncConfig.SyncMode.READ_ONLY
    assert plan["will_contact_provider"] is False
    assert plan["will_ingest_records"] is False
    assert plan["will_send_email"] is False
    assert plan["will_schedule_calendar"] is False
    assert plan["planned_read_model"] == "email_messages"
    assert MockEmailMessage.objects.count() == 0
    assert ExecutiveCalendarEvent.objects.count() == 0
    assert AuditEvent.objects.count() == 0


def test_executive_provider_readiness_summary_counts_ready_and_blocked_configs(client):
    ExecutiveProviderSyncConfig.objects.create(
        provider_type=ExecutiveProviderSyncConfig.ProviderType.EMAIL,
        provider_name="gmail",
        source="gmail_readonly",
        status=ExecutiveProviderSyncConfig.Status.READY_FOR_CONNECTOR,
        scopes=["gmail.readonly"],
        created_by="executive_assistant",
    )
    ExecutiveProviderSyncConfig.objects.create(
        provider_type=ExecutiveProviderSyncConfig.ProviderType.CALENDAR,
        provider_name="google_calendar",
        source="google_calendar_readonly",
        status=ExecutiveProviderSyncConfig.Status.PLANNED,
        created_by="executive_assistant",
    )

    response = client.get("/api/v1/executive-assistant/provider-readiness-summary/")

    assert response.status_code == 200
    summary = response.json()["provider_readiness_summary"]
    assert summary["total"] == 2
    assert summary["ready"] == 1
    assert summary["blocked"] == 1
    assert summary["external_action_enabled"] is False
    assert summary["real_provider_connections_enabled"] is False
    assert {item["connector_key"] for item in summary["items"]} == {"gmail_readonly", "google_calendar_readonly"}


def test_executive_provider_sync_config_dry_run_does_not_contact_provider_or_ingest_records(client):
    config = ExecutiveProviderSyncConfig.objects.create(
        provider_type=ExecutiveProviderSyncConfig.ProviderType.CALENDAR,
        provider_name="google_calendar",
        source="google_calendar_readonly",
        status=ExecutiveProviderSyncConfig.Status.READY_FOR_CONNECTOR,
        scopes=["calendar.readonly"],
        created_by="executive_assistant",
    )

    response = client.post(
        f"/api/v1/executive-assistant/provider-sync-configs/{config.id}/dry-run/",
        data=json.dumps({}),
        content_type="application/json",
        headers=headers("ea-provider-sync-dry-run-1"),
    )

    assert response.status_code == 200
    readiness = response.json()["readiness"]
    assert readiness["ready"] is True
    assert readiness["connector"]["connector_key"] == "google_calendar_readonly"
    assert readiness["dry_run"]["attempted_external_connection"] is False
    assert readiness["dry_run"]["records_ingested"] == 0
    assert MockEmailMessage.objects.count() == 0
    assert ExecutiveCalendarEvent.objects.count() == 0
    assert AuditEvent.objects.filter(
        action="executive_assistant.provider_sync_config.dry_run",
        correlation_id="corr-ea-provider-sync-dry-run-1",
        metadata__external_action_enabled=False,
        metadata__records_ingested=0,
    ).exists()


def test_executive_provider_sync_config_dry_run_blocks_unready_config(client):
    config = ExecutiveProviderSyncConfig.objects.create(
        provider_type=ExecutiveProviderSyncConfig.ProviderType.EMAIL,
        provider_name="gmail",
        source="gmail_readonly",
        status=ExecutiveProviderSyncConfig.Status.PLANNED,
        created_by="executive_assistant",
    )

    response = client.post(
        f"/api/v1/executive-assistant/provider-sync-configs/{config.id}/dry-run/",
        data=json.dumps({}),
        content_type="application/json",
        headers=headers("ea-provider-sync-dry-run-2"),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EXECUTIVE_PROVIDER_CONNECTOR_BLOCKED"
    assert not AuditEvent.objects.filter(action="executive_assistant.provider_sync_config.dry_run").exists()


def test_executive_brief_create_rejects_invalid_type(client):
    response = client.post(
        "/api/v1/executive-assistant/briefs/create/",
        data=json.dumps({"title": "Bad brief", "brief_type": "SEND_EMAIL"}),
        content_type="application/json",
        headers=headers("executive-brief-4"),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_EXECUTIVE_BRIEF_PAYLOAD"
    assert ExecutiveBrief.objects.count() == 0


def test_executive_read_only_email_ingest_routes_message_without_send_capability(client):
    response = client.post(
        "/api/v1/executive-assistant/email-ingest/read-only/",
        data=json.dumps(
            {
                "source": "gmail_readonly",
                "external_event_id": "readonly-msg-1",
                "sender": "client@example.com",
                "subject": "Please approve this decision",
                "body": "Can you choose and sign off?",
            }
        ),
        content_type="application/json",
        headers=headers("ea-readonly-email-1"),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"]["source"] == "gmail_readonly"
    assert body["email"]["classification"] == MockEmailMessage.Classification.DECISION
    assert body["email"]["proposed_action"]["type"] == "REQUEST_INTERNAL_DECISION"
    assert body["email"]["proposed_action"]["dry_run"] is True
    assert MockEmailMessage.objects.count() == 1
    assert AuditEvent.objects.filter(action="mailbox.mock_email.ingested", correlation_id="corr-ea-readonly-email-1").exists()


def test_executive_read_only_email_ingest_rejects_send_capable_source(client):
    response = client.post(
        "/api/v1/executive-assistant/email-ingest/read-only/",
        data=json.dumps(
            {
                "source": "smtp_send",
                "external_event_id": "readonly-msg-2",
                "sender": "client@example.com",
                "subject": "Hello",
                "body": "Hello",
            }
        ),
        content_type="application/json",
        headers=headers("ea-readonly-email-2"),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_EXECUTIVE_BRIEF_PAYLOAD"
    assert MockEmailMessage.objects.count() == 0


def test_executive_read_only_email_batch_ingest_accepts_multiple_records(client):
    response = client.post(
        "/api/v1/executive-assistant/email-ingest/read-only/batch/",
        data=json.dumps(
            {
                "emails": [
                    {
                        "source": "gmail_readonly",
                        "external_event_id": "readonly-batch-1",
                        "sender": "client@example.com",
                        "subject": "Follow up",
                        "body": "Please follow up.",
                    },
                    {
                        "source": "gmail_readonly",
                        "external_event_id": "readonly-batch-2",
                        "sender": "vendor@example.com",
                        "subject": "Invoice",
                        "body": "Attached is invoice 22.",
                    },
                ]
            }
        ),
        content_type="application/json",
        headers=headers("ea-readonly-email-batch-1"),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["created_count"] == 2
    assert body["existing_count"] == 0
    assert len(body["emails"]) == 2
    assert MockEmailMessage.objects.count() == 2


def test_executive_read_only_calendar_ingest_creates_visible_calendar_event(client):
    response = client.post(
        "/api/v1/executive-assistant/calendar/ingest/read-only/",
        data=json.dumps(
            {
                "source": "google_calendar_readonly",
                "external_event_id": "cal-1",
                "title": "Pilot customer review",
                "starts_at": "2026-10-02T10:00:00Z",
                "ends_at": "2026-10-02T11:00:00Z",
                "organizer": "ops@example.com",
                "attendees": ["client@example.com"],
                "location": "Zoom",
            }
        ),
        content_type="application/json",
        headers=headers("ea-calendar-1"),
    )

    assert response.status_code == 201
    body = response.json()["calendar_event"]
    assert body["title"] == "Pilot customer review"
    assert body["status"] == ExecutiveCalendarEvent.Status.CONFIRMED
    assert body["no_external_schedule"] is True
    assert ExecutiveCalendarEvent.objects.count() == 1
    assert AuditEvent.objects.filter(action="executive_assistant.calendar_event.ingested", correlation_id="corr-ea-calendar-1").exists()


def test_executive_calendar_events_list_filters_by_status(client):
    ExecutiveCalendarEvent.objects.create(
        source="calendar_readonly",
        external_event_id="cal-list-1",
        title="Confirmed event",
        starts_at=timezone.now() + timezone.timedelta(hours=1),
        ends_at=timezone.now() + timezone.timedelta(hours=2),
        created_by="executive_assistant",
    )
    ExecutiveCalendarEvent.objects.create(
        source="calendar_readonly",
        external_event_id="cal-list-2",
        title="Tentative event",
        starts_at=timezone.now() + timezone.timedelta(hours=3),
        ends_at=timezone.now() + timezone.timedelta(hours=4),
        status=ExecutiveCalendarEvent.Status.TENTATIVE,
        created_by="executive_assistant",
    )

    response = client.get("/api/v1/executive-assistant/calendar/events/", {"status": ExecutiveCalendarEvent.Status.TENTATIVE})

    assert response.status_code == 200
    events = response.json()["calendar_events"]
    assert len(events) == 1
    assert events[0]["title"] == "Tentative event"


def test_executive_read_only_calendar_batch_ingest_accepts_multiple_events(client):
    response = client.post(
        "/api/v1/executive-assistant/calendar/ingest/read-only/batch/",
        data=json.dumps(
            {
                "events": [
                    {
                        "source": "google_calendar_readonly",
                        "external_event_id": "cal-batch-1",
                        "title": "Morning review",
                        "starts_at": "2026-10-02T08:00:00Z",
                        "ends_at": "2026-10-02T08:30:00Z",
                    },
                    {
                        "source": "google_calendar_readonly",
                        "external_event_id": "cal-batch-2",
                        "title": "Customer call",
                        "starts_at": "2026-10-02T12:00:00Z",
                        "ends_at": "2026-10-02T13:00:00Z",
                        "attendees": ["client@example.com"],
                    },
                ]
            }
        ),
        content_type="application/json",
        headers=headers("ea-calendar-batch-1"),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["created_count"] == 2
    assert body["existing_count"] == 0
    assert len(body["calendar_events"]) == 2
    assert ExecutiveCalendarEvent.objects.count() == 2


def test_executive_email_draft_create_from_message_is_internal_only_and_audited(client):
    message = MockEmailMessage.objects.create(
        source="gmail_mock",
        external_event_id="msg-draft-1",
        sender="client@example.com",
        subject="Decision needed",
        body="Can you approve this?",
        classification=MockEmailMessage.Classification.DECISION,
        proposed_action={"type": "REQUEST_INTERNAL_DECISION"},
        rule_decision=RuleEvaluation.Decision.NEEDS_MORE_DATA,
    )

    response = client.post(
        "/api/v1/executive-assistant/email-drafts/create/",
        data=json.dumps({"source_message_id": str(message.id)}),
        content_type="application/json",
        headers=headers("email-draft-1"),
    )

    assert response.status_code == 201
    body = response.json()["email_draft"]
    assert body["source_message_id"] == str(message.id)
    assert body["draft_type"] == ExecutiveEmailDraft.DraftType.REPLY
    assert body["to_recipients"] == ["client@example.com"]
    assert body["subject"] == "Re: Decision needed"
    assert body["review_status"] == ExecutiveEmailDraft.ReviewStatus.NEEDS_REVIEW
    assert body["no_external_send"] is True
    assert "review the decision" in body["body"]
    assert ExecutiveEmailDraft.objects.count() == 1
    assert AuditEvent.objects.filter(
        action="executive_assistant.email_draft.created",
        correlation_id="corr-email-draft-1",
        metadata__no_external_send=True,
        metadata__requires_approval_before_external_action=True,
    ).exists()


def test_executive_email_draft_create_accepts_explicit_safe_draft_content(client):
    message = MockEmailMessage.objects.create(
        source="gmail_mock",
        external_event_id="msg-draft-2",
        sender="lead@example.com",
        subject="Follow up",
        body="Please follow up.",
        classification=MockEmailMessage.Classification.TASK,
        proposed_action={"type": "PROPOSE_TASK"},
        rule_decision=RuleEvaluation.Decision.NEEDS_MORE_DATA,
    )

    response = client.post(
        "/api/v1/executive-assistant/email-drafts/create/",
        data=json.dumps(
            {
                "source_message_id": str(message.id),
                "to_recipients": ["lead@example.com"],
                "cc_recipients": ["ops@example.com"],
                "subject": "Re: Follow up",
                "body": "Thanks, I am tracking this internally.",
                "rationale": "Acknowledges receipt without committing externally.",
            }
        ),
        content_type="application/json",
        headers=headers("email-draft-2"),
    )

    assert response.status_code == 201
    body = response.json()["email_draft"]
    assert body["cc_recipients"] == ["ops@example.com"]
    assert body["body"] == "Thanks, I am tracking this internally."
    assert body["rationale"] == "Acknowledges receipt without committing externally."


def test_executive_email_draft_create_is_idempotent(client):
    message = MockEmailMessage.objects.create(
        source="gmail_mock",
        external_event_id="msg-draft-3",
        sender="client@example.com",
        subject="Question",
        body="Question",
        classification=MockEmailMessage.Classification.INFORMATION,
        proposed_action={"type": "STORE_INFORMATION"},
        rule_decision=RuleEvaluation.Decision.NEEDS_MORE_DATA,
    )
    payload = {"source_message_id": str(message.id)}

    first = client.post("/api/v1/executive-assistant/email-drafts/create/", data=json.dumps(payload), content_type="application/json", headers=headers("email-draft-3"))
    second = client.post("/api/v1/executive-assistant/email-drafts/create/", data=json.dumps(payload), content_type="application/json", headers=headers("email-draft-3"))

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()
    assert ExecutiveEmailDraft.objects.count() == 1


def test_executive_email_draft_create_returns_not_found_for_missing_source(client):
    response = client.post(
        "/api/v1/executive-assistant/email-drafts/create/",
        data=json.dumps({"source_message_id": "00000000-0000-0000-0000-000000000000"}),
        content_type="application/json",
        headers=headers("email-draft-missing"),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "EMAIL_MESSAGE_NOT_FOUND"


def test_executive_email_drafts_list_filters_by_review_status(client):
    ExecutiveEmailDraft.objects.create(
        draft_type=ExecutiveEmailDraft.DraftType.REPLY,
        to_recipients=["client@example.com"],
        subject="Re: Hello",
        body="Thanks.",
        created_by="executive_assistant",
    )
    ExecutiveEmailDraft.objects.create(
        draft_type=ExecutiveEmailDraft.DraftType.REPLY,
        to_recipients=["client@example.com"],
        subject="Re: Old",
        body="No.",
        review_status=ExecutiveEmailDraft.ReviewStatus.REJECTED,
        created_by="executive_assistant",
    )

    response = client.get(
        "/api/v1/executive-assistant/email-drafts/",
        {"review_status": ExecutiveEmailDraft.ReviewStatus.NEEDS_REVIEW},
    )

    assert response.status_code == 200
    body = response.json()["email_drafts"]
    assert len(body) == 1
    assert body[0]["subject"] == "Re: Hello"


def test_executive_email_drafts_list_rejects_invalid_filter(client):
    response = client.get("/api/v1/executive-assistant/email-drafts/", {"review_status": "SEND_NOW"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_EXECUTIVE_EMAIL_DRAFT_FILTER"


def test_executive_email_draft_review_approves_draft_without_external_send(client):
    draft = ExecutiveEmailDraft.objects.create(
        draft_type=ExecutiveEmailDraft.DraftType.REPLY,
        to_recipients=["client@example.com"],
        subject="Re: Decision",
        body="Thanks. I will review internally.",
        created_by="executive_assistant",
    )

    response = client.post(
        f"/api/v1/executive-assistant/email-drafts/{draft.id}/review/",
        data=json.dumps({"decision": ExecutiveEmailDraft.ReviewStatus.APPROVED, "review_note": "Safe acknowledgement."}),
        content_type="application/json",
        headers=headers("email-draft-review-1"),
    )

    assert response.status_code == 200
    body = response.json()["email_draft"]
    assert body["review_status"] == ExecutiveEmailDraft.ReviewStatus.APPROVED
    assert body["reviewed_by"] == "executive_assistant"
    assert body["review_note"] == "Safe acknowledgement."
    assert body["no_external_send"] is True
    draft.refresh_from_db()
    assert draft.review_status == ExecutiveEmailDraft.ReviewStatus.APPROVED
    assert AuditEvent.objects.filter(
        action="executive_assistant.email_draft.reviewed",
        correlation_id="corr-email-draft-review-1",
        metadata__decision=ExecutiveEmailDraft.ReviewStatus.APPROVED,
        metadata__external_send_enabled=False,
    ).exists()


def test_executive_email_draft_review_rejects_draft(client):
    draft = ExecutiveEmailDraft.objects.create(
        draft_type=ExecutiveEmailDraft.DraftType.REPLY,
        to_recipients=["client@example.com"],
        subject="Re: Bad commitment",
        body="I commit to doing this externally.",
        created_by="executive_assistant",
    )

    response = client.post(
        f"/api/v1/executive-assistant/email-drafts/{draft.id}/review/",
        data=json.dumps({"decision": ExecutiveEmailDraft.ReviewStatus.REJECTED, "review_note": "Too much commitment."}),
        content_type="application/json",
        headers=headers("email-draft-review-2"),
    )

    assert response.status_code == 200
    body = response.json()["email_draft"]
    assert body["review_status"] == ExecutiveEmailDraft.ReviewStatus.REJECTED
    assert body["review_note"] == "Too much commitment."
    draft.refresh_from_db()
    assert draft.review_status == ExecutiveEmailDraft.ReviewStatus.REJECTED


def test_executive_email_draft_review_is_idempotent(client):
    draft = ExecutiveEmailDraft.objects.create(
        draft_type=ExecutiveEmailDraft.DraftType.REPLY,
        to_recipients=["client@example.com"],
        subject="Re: Hello",
        body="Thanks.",
        created_by="executive_assistant",
    )
    payload = {"decision": ExecutiveEmailDraft.ReviewStatus.APPROVED}
    url = f"/api/v1/executive-assistant/email-drafts/{draft.id}/review/"

    first = client.post(url, data=json.dumps(payload), content_type="application/json", headers=headers("email-draft-review-3"))
    second = client.post(url, data=json.dumps(payload), content_type="application/json", headers=headers("email-draft-review-3"))

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert AuditEvent.objects.filter(action="executive_assistant.email_draft.reviewed").count() == 1


def test_executive_email_draft_review_blocks_already_reviewed_draft(client):
    draft = ExecutiveEmailDraft.objects.create(
        draft_type=ExecutiveEmailDraft.DraftType.REPLY,
        to_recipients=["client@example.com"],
        subject="Re: Reviewed",
        body="Thanks.",
        review_status=ExecutiveEmailDraft.ReviewStatus.APPROVED,
        created_by="executive_assistant",
    )

    response = client.post(
        f"/api/v1/executive-assistant/email-drafts/{draft.id}/review/",
        data=json.dumps({"decision": ExecutiveEmailDraft.ReviewStatus.REJECTED}),
        content_type="application/json",
        headers=headers("email-draft-review-4"),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EXECUTIVE_BRIEF_BLOCKED"


def test_executive_email_draft_approval_request_requires_approved_draft(client):
    draft = ExecutiveEmailDraft.objects.create(
        draft_type=ExecutiveEmailDraft.DraftType.REPLY,
        to_recipients=["client@example.com"],
        subject="Re: Pending",
        body="Thanks.",
        created_by="executive_assistant",
    )

    response = client.post(
        f"/api/v1/executive-assistant/email-drafts/{draft.id}/approval-request/",
        data=json.dumps({}),
        content_type="application/json",
        headers=headers("email-draft-approval-1"),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EXECUTIVE_BRIEF_BLOCKED"
    assert ApprovalRequest.objects.count() == 0


def test_executive_email_draft_approval_request_creates_pending_send_approval_without_sending(client):
    draft = ExecutiveEmailDraft.objects.create(
        draft_type=ExecutiveEmailDraft.DraftType.REPLY,
        to_recipients=["client@example.com"],
        cc_recipients=["ops@example.com"],
        subject="Re: Decision",
        body="Thanks. I will review internally.",
        review_status=ExecutiveEmailDraft.ReviewStatus.APPROVED,
        created_by="executive_assistant",
    )

    response = client.post(
        f"/api/v1/executive-assistant/email-drafts/{draft.id}/approval-request/",
        data=json.dumps({"expires_in_hours": 12}),
        content_type="application/json",
        headers=headers("email-draft-approval-2"),
    )

    assert response.status_code == 201
    approval = response.json()["approval"]
    assert approval["subject_type"] == "executive_assistant.ExecutiveEmailDraft"
    assert approval["subject_id"] == str(draft.id)
    assert approval["action"] == "executive_assistant.email_draft.send"
    assert approval["status"] == ApprovalRequest.Status.PENDING
    assert approval["action_payload"]["to_recipients"] == ["client@example.com"]
    assert approval["action_payload"]["cc_recipients"] == ["ops@example.com"]
    assert approval["action_payload"]["external_send_enabled"] is False
    assert approval["action_payload"]["requires_provider_adapter"] is True
    assert AuditEvent.objects.filter(
        action="executive_assistant.email_draft.approval_requested",
        correlation_id="corr-email-draft-approval-2",
        metadata__external_send_enabled=False,
    ).exists()


def test_executive_email_draft_approval_request_is_idempotent(client):
    draft = ExecutiveEmailDraft.objects.create(
        draft_type=ExecutiveEmailDraft.DraftType.REPLY,
        to_recipients=["client@example.com"],
        subject="Re: Hello",
        body="Thanks.",
        review_status=ExecutiveEmailDraft.ReviewStatus.APPROVED,
        created_by="executive_assistant",
    )
    payload = {"expires_in_hours": 12}
    url = f"/api/v1/executive-assistant/email-drafts/{draft.id}/approval-request/"

    first = client.post(url, data=json.dumps(payload), content_type="application/json", headers=headers("email-draft-approval-3"))
    second = client.post(url, data=json.dumps(payload), content_type="application/json", headers=headers("email-draft-approval-3"))

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()
    assert ApprovalRequest.objects.count() == 1


def test_executive_email_draft_approval_request_reuses_existing_pending_approval(client):
    draft = ExecutiveEmailDraft.objects.create(
        draft_type=ExecutiveEmailDraft.DraftType.REPLY,
        to_recipients=["client@example.com"],
        subject="Re: Hello",
        body="Thanks.",
        review_status=ExecutiveEmailDraft.ReviewStatus.APPROVED,
        created_by="executive_assistant",
    )
    url = f"/api/v1/executive-assistant/email-drafts/{draft.id}/approval-request/"

    first = client.post(url, data=json.dumps({}), content_type="application/json", headers=headers("email-draft-approval-4a"))
    second = client.post(url, data=json.dumps({}), content_type="application/json", headers=headers("email-draft-approval-4b"))

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["approval"]["id"] == second.json()["approval"]["id"]
    assert ApprovalRequest.objects.count() == 1


def test_executive_briefs_list_filters_by_type_and_status(client):
    ExecutiveBrief.objects.create(
        brief_type=ExecutiveBrief.BriefType.INBOX_TRIAGE,
        title="Inbox triage",
        summary="Review inbox.",
        created_by="executive_assistant",
    )
    ExecutiveBrief.objects.create(
        brief_type=ExecutiveBrief.BriefType.FOLLOW_UPS,
        title="Archived follow-ups",
        summary="Old follow-ups.",
        status=ExecutiveBrief.Status.ARCHIVED,
        created_by="executive_assistant",
    )

    response = client.get(
        "/api/v1/executive-assistant/briefs/",
        {"brief_type": ExecutiveBrief.BriefType.INBOX_TRIAGE, "status": ExecutiveBrief.Status.READY},
    )

    assert response.status_code == 200
    body = response.json()["executive_briefs"]
    assert len(body) == 1
    assert body[0]["title"] == "Inbox triage"


def test_executive_briefs_list_rejects_invalid_filter(client):
    response = client.get("/api/v1/executive-assistant/briefs/", {"brief_type": "SEND_EMAIL"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_EXECUTIVE_BRIEF_FILTER"


@pytest.fixture
def executive_brief_with_follow_up(active_objective):
    task = Task.objects.create(
        objective=active_objective,
        title="Resolve billing question",
        status=Task.Status.BLOCKED,
        business_outcome="Billing question resolved.",
        created_by="chief",
    )
    return ExecutiveBrief.objects.create(
        brief_type=ExecutiveBrief.BriefType.FOLLOW_UPS,
        title="Follow-up brief",
        summary="One follow-up.",
        follow_ups=[{"task_id": str(task.id), "title": task.title, "reason": "blocked"}],
        created_by="executive_assistant",
    )


def test_executive_brief_task_proposal_creates_draft_task_and_audit(client, active_objective, executive_brief_with_follow_up):
    response = client.post(
        f"/api/v1/executive-assistant/briefs/{executive_brief_with_follow_up.id}/tasks/propose/",
        data=json.dumps({"objective_id": str(active_objective.id)}),
        content_type="application/json",
        headers=headers("executive-task-proposal-1"),
    )

    assert response.status_code == 201
    body = response.json()["task_proposals"]
    assert len(body) == 1
    assert body[0]["no_external_send"] is True
    assert body[0]["review_status"] == ExecutiveBriefTaskProposal.ReviewStatus.PENDING
    assert body[0]["title"] == "Follow up: Resolve billing question"
    assert ExecutiveBriefTaskProposal.objects.count() == 1
    proposed_task = Task.objects.get(id=body[0]["task_id"])
    assert proposed_task.status == Task.Status.DRAFT
    assert proposed_task.owner_agent_id == "executive_assistant"
    assert proposed_task.acceptance_criteria.count() == 1
    assert AuditEvent.objects.filter(
        action="executive_assistant.tasks.proposed",
        correlation_id="corr-executive-task-proposal-1",
        metadata__no_external_send=True,
    ).exists()


def test_executive_brief_task_proposal_is_idempotent(client, active_objective, executive_brief_with_follow_up):
    payload = {"objective_id": str(active_objective.id)}
    url = f"/api/v1/executive-assistant/briefs/{executive_brief_with_follow_up.id}/tasks/propose/"

    first = client.post(url, data=json.dumps(payload), content_type="application/json", headers=headers("executive-task-proposal-2"))
    second = client.post(url, data=json.dumps(payload), content_type="application/json", headers=headers("executive-task-proposal-2"))

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()
    assert ExecutiveBriefTaskProposal.objects.count() == 1


def test_executive_brief_task_proposal_rejects_brief_without_followups(client, active_objective):
    brief = ExecutiveBrief.objects.create(
        brief_type=ExecutiveBrief.BriefType.WEEKLY_REVIEW_PREP,
        title="Empty brief",
        summary="Nothing to do.",
        created_by="executive_assistant",
    )

    response = client.post(
        f"/api/v1/executive-assistant/briefs/{brief.id}/tasks/propose/",
        data=json.dumps({"objective_id": str(active_objective.id)}),
        content_type="application/json",
        headers=headers("executive-task-proposal-3"),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EXECUTIVE_BRIEF_BLOCKED"
    assert ExecutiveBriefTaskProposal.objects.count() == 0


def test_executive_brief_api_detail_returns_brief_and_task_proposals(client, executive_task_proposal):
    response = client.get(f"/api/v1/executive-assistant/briefs/{executive_task_proposal.brief_id}/")

    assert response.status_code == 200
    body = response.json()
    assert body["executive_brief"]["id"] == str(executive_task_proposal.brief_id)
    assert body["executive_brief"]["title"] == "Follow-up brief"
    assert len(body["task_proposals"]) == 1
    assert body["task_proposals"][0]["id"] == str(executive_task_proposal.id)
    assert body["task_proposals"][0]["external_key"] == executive_task_proposal.external_key
    assert AuditEvent.objects.count() == 0


def test_executive_brief_api_detail_returns_empty_task_proposals(client):
    brief = ExecutiveBrief.objects.create(
        brief_type=ExecutiveBrief.BriefType.INBOX_TRIAGE,
        title="Inbox detail",
        summary="Inbox detail.",
        created_by="executive_assistant",
    )

    response = client.get(f"/api/v1/executive-assistant/briefs/{brief.id}/")

    assert response.status_code == 200
    body = response.json()
    assert body["executive_brief"]["id"] == str(brief.id)
    assert body["task_proposals"] == []


def test_executive_brief_api_detail_returns_not_found(client):
    response = client.get("/api/v1/executive-assistant/briefs/00000000-0000-0000-0000-000000000000/")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "EXECUTIVE_BRIEF_NOT_FOUND"


def test_executive_brief_archive_api_archives_and_audits(client, executive_brief_with_follow_up):
    response = client.post(
        f"/api/v1/executive-assistant/briefs/{executive_brief_with_follow_up.id}/archive/",
        data=json.dumps({}),
        content_type="application/json",
        headers=headers("executive-brief-archive-1"),
    )

    assert response.status_code == 200
    body = response.json()["executive_brief"]
    assert body["status"] == ExecutiveBrief.Status.ARCHIVED
    assert body["no_external_send"] is True
    executive_brief_with_follow_up.refresh_from_db()
    assert executive_brief_with_follow_up.status == ExecutiveBrief.Status.ARCHIVED
    assert AuditEvent.objects.filter(
        action="executive_assistant.brief.archived",
        correlation_id="corr-executive-brief-archive-1",
        metadata__no_external_send=True,
    ).exists()


def test_executive_brief_archive_api_is_idempotent(client, executive_brief_with_follow_up):
    url = f"/api/v1/executive-assistant/briefs/{executive_brief_with_follow_up.id}/archive/"

    first = client.post(url, data=json.dumps({}), content_type="application/json", headers=headers("executive-brief-archive-2"))
    second = client.post(url, data=json.dumps({}), content_type="application/json", headers=headers("executive-brief-archive-2"))

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert AuditEvent.objects.filter(action="executive_assistant.brief.archived").count() == 1


def test_executive_brief_archive_api_rejects_reused_idempotency_key_for_another_brief(client, executive_brief_with_follow_up):
    other = ExecutiveBrief.objects.create(
        brief_type=ExecutiveBrief.BriefType.FOLLOW_UPS,
        title="Other brief",
        summary="Another brief.",
        created_by="executive_assistant",
    )
    client.post(
        f"/api/v1/executive-assistant/briefs/{executive_brief_with_follow_up.id}/archive/",
        data=json.dumps({}),
        content_type="application/json",
        headers=headers("executive-brief-archive-3"),
    )

    response = client.post(
        f"/api/v1/executive-assistant/briefs/{other.id}/archive/",
        data=json.dumps({}),
        content_type="application/json",
        headers=headers("executive-brief-archive-3"),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    other.refresh_from_db()
    assert other.status == ExecutiveBrief.Status.READY


def test_executive_brief_archive_api_rejects_archived_brief(client, executive_brief_with_follow_up):
    executive_brief_with_follow_up.status = ExecutiveBrief.Status.ARCHIVED
    executive_brief_with_follow_up.save(update_fields=["status"])

    response = client.post(
        f"/api/v1/executive-assistant/briefs/{executive_brief_with_follow_up.id}/archive/",
        data=json.dumps({}),
        content_type="application/json",
        headers=headers("executive-brief-archive-4"),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EXECUTIVE_BRIEF_BLOCKED"


@pytest.fixture
def executive_task_proposal(active_objective, executive_brief_with_follow_up):
    task = Task.objects.create(
        objective=active_objective,
        title="Follow up: Resolve billing question",
        status=Task.Status.DRAFT,
        owner_agent_id="executive_assistant",
        business_outcome="Resolve the follow-up.",
        created_by="executive_assistant",
    )
    return ExecutiveBriefTaskProposal.objects.create(
        brief=executive_brief_with_follow_up,
        task_id=task.id,
        follow_up_index=0,
        external_key=f"executive-brief:{executive_brief_with_follow_up.id}:follow-up:0",
        title=task.title,
        status=task.status,
        created_by="executive_assistant",
    )


def test_executive_task_proposal_review_accepts_and_plans_task(client, executive_task_proposal):
    response = client.post(
        f"/api/v1/executive-assistant/task-proposals/{executive_task_proposal.id}/review/",
        data=json.dumps({"decision": ExecutiveBriefTaskProposal.ReviewStatus.ACCEPTED}),
        content_type="application/json",
        headers=headers("executive-task-review-1"),
    )

    assert response.status_code == 200
    body = response.json()["task_proposal"]
    assert body["review_status"] == ExecutiveBriefTaskProposal.ReviewStatus.ACCEPTED
    assert body["status"] == Task.Status.PLANNED
    assert body["reviewed_by"] == "executive_assistant"
    assert body["reviewed_at"] is not None
    assert body["review_note"] == ""
    task = Task.objects.get(id=executive_task_proposal.task_id)
    assert task.status == Task.Status.PLANNED
    assert AuditEvent.objects.filter(
        action="executive_assistant.task_proposal.reviewed",
        correlation_id="corr-executive-task-review-1",
        metadata__decision=ExecutiveBriefTaskProposal.ReviewStatus.ACCEPTED,
    ).exists()


def test_executive_task_proposal_review_dismisses_and_cancels_task(client, executive_task_proposal):
    response = client.post(
        f"/api/v1/executive-assistant/task-proposals/{executive_task_proposal.id}/review/",
        data=json.dumps({"decision": ExecutiveBriefTaskProposal.ReviewStatus.DISMISSED, "review_note": "Not needed this week."}),
        content_type="application/json",
        headers=headers("executive-task-review-2"),
    )

    assert response.status_code == 200
    body = response.json()["task_proposal"]
    assert body["review_status"] == ExecutiveBriefTaskProposal.ReviewStatus.DISMISSED
    assert body["status"] == Task.Status.CANCELLED
    assert body["review_note"] == "Not needed this week."
    task = Task.objects.get(id=executive_task_proposal.task_id)
    assert task.status == Task.Status.CANCELLED


def test_executive_task_proposal_review_is_idempotent(client, executive_task_proposal):
    payload = {"decision": ExecutiveBriefTaskProposal.ReviewStatus.ACCEPTED}
    url = f"/api/v1/executive-assistant/task-proposals/{executive_task_proposal.id}/review/"

    first = client.post(url, data=json.dumps(payload), content_type="application/json", headers=headers("executive-task-review-3"))
    second = client.post(url, data=json.dumps(payload), content_type="application/json", headers=headers("executive-task-review-3"))

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()


def test_executive_task_proposal_review_rejects_already_reviewed(client, executive_task_proposal):
    executive_task_proposal.review_status = ExecutiveBriefTaskProposal.ReviewStatus.ACCEPTED
    executive_task_proposal.save(update_fields=["review_status"])

    response = client.post(
        f"/api/v1/executive-assistant/task-proposals/{executive_task_proposal.id}/review/",
        data=json.dumps({"decision": ExecutiveBriefTaskProposal.ReviewStatus.DISMISSED}),
        content_type="application/json",
        headers=headers("executive-task-review-4"),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EXECUTIVE_BRIEF_BLOCKED"


def test_executive_task_proposals_list_filters_by_review_status(client, executive_task_proposal):
    executive_task_proposal.review_status = ExecutiveBriefTaskProposal.ReviewStatus.ACCEPTED
    executive_task_proposal.save(update_fields=["review_status"])

    response = client.get(
        "/api/v1/executive-assistant/task-proposals/",
        {"review_status": ExecutiveBriefTaskProposal.ReviewStatus.ACCEPTED},
    )

    assert response.status_code == 200
    body = response.json()["task_proposals"]
    assert len(body) == 1
    assert body[0]["id"] == str(executive_task_proposal.id)
    assert body[0]["review_status"] == ExecutiveBriefTaskProposal.ReviewStatus.ACCEPTED


def test_executive_task_proposals_list_rejects_invalid_filter(client):
    response = client.get("/api/v1/executive-assistant/task-proposals/", {"review_status": "APPROVE_AND_SEND"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_EXECUTIVE_TASK_PROPOSAL_FILTER"


def test_executive_task_proposal_detail_returns_proposal_and_brief(client, executive_task_proposal):
    response = client.get(f"/api/v1/executive-assistant/task-proposals/{executive_task_proposal.id}/")

    assert response.status_code == 200
    body = response.json()
    assert body["task_proposal"]["id"] == str(executive_task_proposal.id)
    assert body["task_proposal"]["task_id"] == str(executive_task_proposal.task_id)
    assert body["task_proposal"]["review_status"] == ExecutiveBriefTaskProposal.ReviewStatus.PENDING
    assert body["task_proposal"]["reviewed_by"] == ""
    assert body["task_proposal"]["reviewed_at"] is None
    assert body["task_proposal"]["review_note"] == ""
    assert body["executive_brief"]["id"] == str(executive_task_proposal.brief_id)
    assert body["executive_brief"]["title"] == "Follow-up brief"
    assert AuditEvent.objects.count() == 0


def test_executive_task_proposal_detail_returns_not_found(client):
    response = client.get("/api/v1/executive-assistant/task-proposals/00000000-0000-0000-0000-000000000000/")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "EXECUTIVE_TASK_PROPOSAL_NOT_FOUND"


def test_executive_assistant_dashboard_requires_login(client):
    response = client.get("/executive-assistant/")

    assert response.status_code == 302
    assert response["Location"] == "/admin/login/?next=/executive-assistant/"


def test_executive_assistant_dashboard_renders_briefs_and_proposals(client, executive_task_proposal):
    user = get_user_model().objects.create_user(username="ea-viewer", password="secret")
    client.force_login(user)
    run = RuleEngineRun.objects.create(
        source="gmail_mock",
        external_event_id="msg-ea-work-1",
        event_type="inbound_email.route",
        event_payload={},
        dry_run=True,
        final_decision="require_approval",
        risk_level="high",
        reason_codes=["SENSITIVE_EMAIL_REQUIRES_HUMAN_REVIEW"],
        raw_result={},
    )
    RuleEngineWorkItem.objects.create(
        run=run,
        item_type="ROUTE_REVIEW",
        title="Review sensitive email",
        component="owner_review",
        purpose="review_sensitive_email",
        status=RuleEngineWorkItem.Status.ASSIGNED,
        owner_agent_id="executive_assistant",
    )
    executive_task_proposal.review_status = ExecutiveBriefTaskProposal.ReviewStatus.ACCEPTED
    executive_task_proposal.reviewed_by = "chief"
    executive_task_proposal.reviewed_at = timezone.now()
    executive_task_proposal.review_note = "Include in Monday planning."
    executive_task_proposal.save(update_fields=["review_status", "reviewed_by", "reviewed_at", "review_note"])
    ExecutiveProviderSyncConfig.objects.create(
        provider_type=ExecutiveProviderSyncConfig.ProviderType.EMAIL,
        provider_name="gmail",
        source="gmail_readonly",
        status=ExecutiveProviderSyncConfig.Status.READY_FOR_CONNECTOR,
        scopes=["gmail.readonly"],
        created_by="executive_assistant",
    )

    response = client.get("/executive-assistant/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Executive Assistant" in content
    assert "Queue Snapshot" in content
    assert "Ready Briefs" in content
    assert "Pending Proposals" in content
    assert "Follow-up brief" in content
    assert "Follow up: Resolve billing question" in content
    assert executive_task_proposal.external_key in content
    assert "chief" in content
    assert "Include in Monday planning." in content
    assert "Rule Engine Work" in content
    assert "Review sensitive email" in content
    assert "Provider Readiness Summary" in content
    assert "gmail_readonly" in content


def test_executive_assistant_dashboard_can_complete_rule_engine_work_item(client):
    user = get_user_model().objects.create_user(username="ea-rule-worker", password="secret")
    client.force_login(user)
    run = RuleEngineRun.objects.create(
        source="gmail_mock",
        external_event_id="msg-ea-work-2",
        event_type="inbound_email.route",
        event_payload={},
        dry_run=True,
        final_decision="require_approval",
        risk_level="high",
        reason_codes=["SENSITIVE_EMAIL_REQUIRES_HUMAN_REVIEW"],
        raw_result={},
    )
    item = RuleEngineWorkItem.objects.create(
        run=run,
        item_type="ROUTE_REVIEW",
        title="Review sensitive email",
        component="owner_review",
        purpose="review_sensitive_email",
        status=RuleEngineWorkItem.Status.ASSIGNED,
        owner_agent_id="executive_assistant",
    )

    response = client.post(
        "/executive-assistant/",
        {"action": "complete_rule_engine_work_item", "item_id": str(item.id)},
    )

    assert response.status_code == 302
    item.refresh_from_db()
    assert item.status == RuleEngineWorkItem.Status.COMPLETED
    assert AuditEvent.objects.filter(
        action="governance.rules_engine.work_item.updated",
        actor_id="ea-rule-worker",
        object_id=str(item.id),
    ).exists()


def test_executive_assistant_dashboard_filters_read_only_queues(client, executive_task_proposal):
    user = get_user_model().objects.create_user(username="ea-filter-viewer", password="secret")
    client.force_login(user)
    ExecutiveBrief.objects.create(
        brief_type=ExecutiveBrief.BriefType.INBOX_TRIAGE,
        title="Inbox only brief",
        summary="Inbox queue.",
        created_by="executive_assistant",
    )

    response = client.get(
        "/executive-assistant/",
        {
            "brief_type": ExecutiveBrief.BriefType.FOLLOW_UPS,
            "brief_status": ExecutiveBrief.Status.READY,
            "review_status": ExecutiveBriefTaskProposal.ReviewStatus.PENDING,
        },
    )

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Follow-up brief" in content
    assert "Follow up: Resolve billing question" in content
    assert "Inbox only brief" not in content


def test_executive_assistant_dashboard_can_create_brief(client):
    user = get_user_model().objects.create_user(username="ea-operator", password="secret")
    client.force_login(user)

    response = client.post(
        "/executive-assistant/",
        {
            "action": "create_brief",
            "idempotency_key": "ea-ui-create-brief-1",
            "title": "Dashboard follow-ups",
            "brief_type": ExecutiveBrief.BriefType.FOLLOW_UPS,
            "source_window_days": "7",
        },
    )

    assert response.status_code == 302
    brief = ExecutiveBrief.objects.get(title="Dashboard follow-ups")
    assert brief.brief_type == ExecutiveBrief.BriefType.FOLLOW_UPS
    assert brief.source_window == {"days": 7}
    assert AuditEvent.objects.filter(
        action="executive_assistant.brief.created",
        actor_id="ea-operator",
        correlation_id="dashboard-executive-assistant-create_brief",
    ).exists()


def test_executive_assistant_dashboard_can_propose_tasks(client, active_objective, executive_brief_with_follow_up):
    user = get_user_model().objects.create_user(username="ea-task-operator", password="secret")
    client.force_login(user)

    response = client.post(
        "/executive-assistant/",
        {
            "action": "propose_tasks",
            "brief_id": str(executive_brief_with_follow_up.id),
            "idempotency_key": "ea-ui-propose-1",
            "objective_id": str(active_objective.id),
        },
    )

    assert response.status_code == 302
    proposal = ExecutiveBriefTaskProposal.objects.get(brief=executive_brief_with_follow_up)
    assert proposal.review_status == ExecutiveBriefTaskProposal.ReviewStatus.PENDING
    task = Task.objects.get(id=proposal.task_id)
    assert task.status == Task.Status.DRAFT
    assert task.owner_agent_id == "executive_assistant"
    assert AuditEvent.objects.filter(
        action="executive_assistant.tasks.proposed",
        actor_id="ea-task-operator",
        correlation_id="dashboard-executive-assistant-propose_tasks",
    ).exists()


def test_executive_assistant_dashboard_can_review_task_proposal(client, executive_task_proposal):
    user = get_user_model().objects.create_user(username="ea-reviewer", password="secret")
    client.force_login(user)

    response = client.post(
        "/executive-assistant/",
        {
            "action": "review_proposal",
            "proposal_id": str(executive_task_proposal.id),
            "idempotency_key": "ea-ui-review-1",
            "decision": ExecutiveBriefTaskProposal.ReviewStatus.ACCEPTED,
            "review_note": "Bring into next planning cycle.",
        },
    )

    assert response.status_code == 302
    executive_task_proposal.refresh_from_db()
    task = Task.objects.get(id=executive_task_proposal.task_id)
    assert executive_task_proposal.review_status == ExecutiveBriefTaskProposal.ReviewStatus.ACCEPTED
    assert executive_task_proposal.reviewed_by == "ea-reviewer"
    assert executive_task_proposal.reviewed_at is not None
    assert executive_task_proposal.review_note == "Bring into next planning cycle."
    assert task.status == Task.Status.PLANNED
    assert AuditEvent.objects.filter(
        action="executive_assistant.task_proposal.reviewed",
        actor_id="ea-reviewer",
        correlation_id="dashboard-executive-assistant-review_proposal",
    ).exists()


def test_executive_assistant_dashboard_can_archive_brief(client, executive_brief_with_follow_up):
    user = get_user_model().objects.create_user(username="ea-archiver", password="secret")
    client.force_login(user)

    response = client.post(
        "/executive-assistant/",
        {
            "action": "archive_brief",
            "brief_id": str(executive_brief_with_follow_up.id),
            "idempotency_key": "ea-ui-archive-1",
        },
    )

    assert response.status_code == 302
    executive_brief_with_follow_up.refresh_from_db()
    assert executive_brief_with_follow_up.status == ExecutiveBrief.Status.ARCHIVED
    assert AuditEvent.objects.filter(
        action="executive_assistant.brief.archived",
        actor_id="ea-archiver",
        correlation_id="dashboard-executive-assistant-archive_brief",
        metadata__no_external_send=True,
    ).exists()


def test_executive_assistant_dashboard_archive_is_idempotent(client, executive_brief_with_follow_up):
    user = get_user_model().objects.create_user(username="ea-repeat-archiver", password="secret")
    client.force_login(user)
    payload = {
        "action": "archive_brief",
        "brief_id": str(executive_brief_with_follow_up.id),
        "idempotency_key": "ea-ui-archive-2",
    }

    first = client.post("/executive-assistant/", payload)
    second = client.post("/executive-assistant/", payload)

    assert first.status_code == 302
    assert second.status_code == 302
    executive_brief_with_follow_up.refresh_from_db()
    assert executive_brief_with_follow_up.status == ExecutiveBrief.Status.ARCHIVED
    assert AuditEvent.objects.filter(action="executive_assistant.brief.archived").count() == 1


def test_executive_brief_detail_requires_login(client, executive_brief_with_follow_up):
    response = client.get(f"/executive-assistant/briefs/{executive_brief_with_follow_up.id}/")

    assert response.status_code == 302
    assert response["Location"] == f"/admin/login/?next=/executive-assistant/briefs/{executive_brief_with_follow_up.id}/"


def test_executive_brief_detail_renders_brief_sections_and_proposals(client, executive_task_proposal):
    user = get_user_model().objects.create_user(username="ea-detail-viewer", password="secret")
    client.force_login(user)
    brief = executive_task_proposal.brief
    brief.agenda_items = [{"topic": "Blocked tasks", "count": 1}]
    brief.decisions_needed = [{"approval_id": "", "subject_type": "operations.Task", "action": "operations.task.transition"}]
    brief.inbox_items = [{"sender": "ceo@example.local", "subject": "Please decide", "classification": "DECISION", "proposed_action": {"type": "REQUEST_INTERNAL_DECISION"}}]
    brief.save(update_fields=["agenda_items", "decisions_needed", "inbox_items"])
    executive_task_proposal.review_status = ExecutiveBriefTaskProposal.ReviewStatus.DISMISSED
    executive_task_proposal.reviewed_by = "chief"
    executive_task_proposal.reviewed_at = timezone.now()
    executive_task_proposal.review_note = "Duplicate with existing task."
    executive_task_proposal.save(update_fields=["review_status", "reviewed_by", "reviewed_at", "review_note"])

    response = client.get(f"/executive-assistant/briefs/{brief.id}/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Follow-up brief" in content
    assert "Blocked tasks" in content
    assert "Resolve billing question" in content
    assert "operations.task.transition" in content
    assert "ceo@example.local" in content
    assert executive_task_proposal.external_key in content
    assert "chief" in content
    assert "Duplicate with existing task." in content


def test_executive_brief_detail_hides_archive_for_archived_brief(client, executive_brief_with_follow_up):
    user = get_user_model().objects.create_user(username="ea-archived-viewer", password="secret")
    client.force_login(user)
    executive_brief_with_follow_up.status = ExecutiveBrief.Status.ARCHIVED
    executive_brief_with_follow_up.save(update_fields=["status"])

    response = client.get(f"/executive-assistant/briefs/{executive_brief_with_follow_up.id}/")

    assert response.status_code == 200
    assert "Archive Brief" not in response.content.decode("utf-8")


def test_executive_assistant_dashboard_links_to_brief_detail(client, executive_brief_with_follow_up):
    user = get_user_model().objects.create_user(username="ea-link-viewer", password="secret")
    client.force_login(user)

    response = client.get("/executive-assistant/")

    assert response.status_code == 200
    assert f"/executive-assistant/briefs/{executive_brief_with_follow_up.id}/" in response.content.decode("utf-8")


def test_executive_brief_detail_can_propose_tasks(client, active_objective, executive_brief_with_follow_up):
    user = get_user_model().objects.create_user(username="ea-detail-task-operator", password="secret")
    client.force_login(user)

    response = client.post(
        f"/executive-assistant/briefs/{executive_brief_with_follow_up.id}/",
        {
            "action": "propose_tasks",
            "idempotency_key": "ea-detail-propose-1",
            "objective_id": str(active_objective.id),
        },
    )

    assert response.status_code == 302
    assert response["Location"] == f"/executive-assistant/briefs/{executive_brief_with_follow_up.id}/"
    proposal = ExecutiveBriefTaskProposal.objects.get(brief=executive_brief_with_follow_up)
    assert proposal.review_status == ExecutiveBriefTaskProposal.ReviewStatus.PENDING
    task = Task.objects.get(id=proposal.task_id)
    assert task.owner_agent_id == "executive_assistant"
    assert AuditEvent.objects.filter(
        action="executive_assistant.tasks.proposed",
        actor_id="ea-detail-task-operator",
        correlation_id="dashboard-executive-assistant-propose_tasks",
    ).exists()


def test_executive_brief_detail_can_review_task_proposal(client, executive_task_proposal):
    user = get_user_model().objects.create_user(username="ea-detail-reviewer", password="secret")
    client.force_login(user)

    response = client.post(
        f"/executive-assistant/briefs/{executive_task_proposal.brief_id}/",
        {
            "action": "review_proposal",
            "proposal_id": str(executive_task_proposal.id),
            "idempotency_key": "ea-detail-review-1",
            "decision": ExecutiveBriefTaskProposal.ReviewStatus.ACCEPTED,
            "review_note": "Ready for planning.",
        },
    )

    assert response.status_code == 302
    assert response["Location"] == f"/executive-assistant/briefs/{executive_task_proposal.brief_id}/"
    executive_task_proposal.refresh_from_db()
    task = Task.objects.get(id=executive_task_proposal.task_id)
    assert executive_task_proposal.review_status == ExecutiveBriefTaskProposal.ReviewStatus.ACCEPTED
    assert executive_task_proposal.reviewed_by == "ea-detail-reviewer"
    assert executive_task_proposal.reviewed_at is not None
    assert executive_task_proposal.review_note == "Ready for planning."
    assert task.status == Task.Status.PLANNED
    assert AuditEvent.objects.filter(
        action="executive_assistant.task_proposal.reviewed",
        actor_id="ea-detail-reviewer",
        correlation_id="dashboard-executive-assistant-review_proposal",
    ).exists()


def test_executive_brief_detail_can_archive_brief(client, executive_brief_with_follow_up):
    user = get_user_model().objects.create_user(username="ea-detail-archiver", password="secret")
    client.force_login(user)

    response = client.post(
        f"/executive-assistant/briefs/{executive_brief_with_follow_up.id}/",
        {
            "action": "archive_brief",
            "idempotency_key": "ea-detail-archive-1",
        },
    )

    assert response.status_code == 302
    assert response["Location"] == f"/executive-assistant/briefs/{executive_brief_with_follow_up.id}/"
    executive_brief_with_follow_up.refresh_from_db()
    assert executive_brief_with_follow_up.status == ExecutiveBrief.Status.ARCHIVED
    assert AuditEvent.objects.filter(
        action="executive_assistant.brief.archived",
        actor_id="ea-detail-archiver",
        correlation_id="dashboard-executive-assistant-archive_brief",
    ).exists()


def test_executive_brief_detail_rejects_review_for_other_brief(client, active_objective, executive_task_proposal):
    user = get_user_model().objects.create_user(username="ea-detail-cross-brief", password="secret")
    client.force_login(user)
    other_brief = ExecutiveBrief.objects.create(
        brief_type=ExecutiveBrief.BriefType.FOLLOW_UPS,
        title="Other follow-up brief",
        summary="Other brief.",
        created_by="executive_assistant",
    )

    response = client.post(
        f"/executive-assistant/briefs/{other_brief.id}/",
        {
            "action": "review_proposal",
            "proposal_id": str(executive_task_proposal.id),
            "idempotency_key": "ea-detail-review-other-1",
            "decision": ExecutiveBriefTaskProposal.ReviewStatus.ACCEPTED,
        },
    )

    assert response.status_code == 302
    executive_task_proposal.refresh_from_db()
    task = Task.objects.get(id=executive_task_proposal.task_id)
    assert executive_task_proposal.review_status == ExecutiveBriefTaskProposal.ReviewStatus.PENDING
    assert task.status == Task.Status.DRAFT
    assert not AuditEvent.objects.filter(action="executive_assistant.task_proposal.reviewed").exists()
