import json
from datetime import datetime, time, timedelta
import pytest
from django.utils import timezone
from django.contrib.auth import get_user_model

from core.services import canonical_hash
from governance.models import ApprovalRequest, AuditEvent
from mailbox.models import MockEmailMessage
from operations.models import Task
from portfolio.models import Objective, StrategyVersion
from executive_assistant.ea_engine import (
    CalendarConflictEngine,
    EmailTriageAndDraftEngine,
    MorningExecutiveBriefEngine,
    DelegationTrackerEngine,
)
from executive_assistant.models import (
    DelegatedTaskFollowUp,
    ExecutiveBrief,
    ExecutiveCalendarEvent,
    ExecutiveEmailDraft,
)

pytestmark = pytest.mark.django_db


def headers(key: str = "ea-test-1") -> dict:
    return {
        "HTTP_IDEMPOTENCY_KEY": key,
        "HTTP_X_CORRELATION_ID": f"corr-{key}",
        "HTTP_X_ACTOR_ID": "executive_assistant",
    }


@pytest.fixture
def test_user():
    user_model = get_user_model()
    return user_model.objects.create_user(username="ceo_tester", password="password123")


@pytest.fixture
def strategy():
    return StrategyVersion.objects.create(
        version=1,
        title="Q4 Plan",
        content={},
        status=StrategyVersion.Status.ACTIVE,
    )


@pytest.fixture
def active_objective(strategy):
    return Objective.objects.create(
        code="OBJ-TEST-EA",
        strategy_version=strategy,
        name="Scale Enterprise ARR to $1M",
        business_outcome="Reach 1M ARR",
        status=Objective.Status.ACTIVE,
        owner_agent_id="CEO",
    )


# ==============================================================================
# 1. Calendar Conflict & Reschedule Tests
# ==============================================================================

def test_calendar_conflict_detection():
    now = timezone.now().replace(hour=10, minute=0, second=0, microsecond=0)
    
    # Event 1: 10:00 - 11:00
    e1 = ExecutiveCalendarEvent.objects.create(
        external_event_id="cal-1",
        title="Board Strategy Review",
        starts_at=now,
        ends_at=now + timedelta(hours=1),
        organizer="sharon@example.com",
        created_by="test_user",
    )
    # Event 2: 10:30 - 11:30 (Overlap with Event 1)
    e2 = ExecutiveCalendarEvent.objects.create(
        external_event_id="cal-2",
        title="Customer Demo",
        starts_at=now + timedelta(minutes=30),
        ends_at=now + timedelta(minutes=90),
        organizer="sales@example.com",
        created_by="test_user",
    )
    # Event 3: 11:35 - 12:00 (Buffer violation with Event 2: only 5 min buffer < 15 min)
    e3 = ExecutiveCalendarEvent.objects.create(
        external_event_id="cal-3",
        title="1:1 Sync with VP Product",
        starts_at=now + timedelta(minutes=95),
        ends_at=now + timedelta(minutes=120),
        organizer="pm@example.com",
        created_by="test_user",
    )

    conflicts = CalendarConflictEngine.detect_conflicts()
    assert len(conflicts) >= 2
    
    overlap = next(c for c in conflicts if c["conflict_type"] == "OVERLAP")
    assert overlap["severity"] == "HIGH"
    assert overlap["overlap_minutes"] == 30

    buffer_v = next(c for c in conflicts if c["conflict_type"] == "BUFFER_VIOLATION")
    assert buffer_v["severity"] == "MEDIUM"
    assert buffer_v["buffer_available_minutes"] == 5


def test_calendar_reschedule_suggestion():
    # Setup tomorrow 10:00 event
    tomorrow = (timezone.now() + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    conflicting_event = ExecutiveCalendarEvent.objects.create(
        external_event_id="cal-reschedule-target",
        title="Conflicting Sync",
        starts_at=tomorrow,
        ends_at=tomorrow + timedelta(minutes=45),
        organizer="partner@example.com",
        created_by="test_user",
    )

    reschedule_data = CalendarConflictEngine.suggest_reschedule(
        event_id=conflicting_event.id,
        search_days=3,
        slot_duration_minutes=45,
    )

    assert "candidate_slots" in reschedule_data
    assert len(reschedule_data["candidate_slots"]) > 0
    first_slot = reschedule_data["candidate_slots"][0]
    assert first_slot["duration_minutes"] == 45
    assert first_slot["confidence_score"] >= 70


# ==============================================================================
# 2. Email Triage & Draft Engine Tests
# ==============================================================================

def test_email_triage_classification():
    msg_fin = MockEmailMessage.objects.create(
        source="email_readonly",
        external_event_id="msg-fin-1",
        sender="vendor@acme.com",
        subject="URGENT: Outstanding Invoice #4092 Approval",
        body="Please find attached the invoice for AWS infrastructure. Needs immediate payment.",
        classification=MockEmailMessage.Classification.INVOICE,
        proposed_action={"action": "review"},
        rule_decision="ALLOW",
    )
    msg_info = MockEmailMessage.objects.create(
        source="email_readonly",
        external_event_id="msg-info-1",
        sender="newsletter@tech.com",
        subject="Weekly AI Industry Trends",
        body="Here is our summary of recent model releases and benchmark scores.",
        classification=MockEmailMessage.Classification.INFORMATION,
        proposed_action={"action": "archive"},
        rule_decision="ALLOW",
    )

    triaged = EmailTriageAndDraftEngine.triage_emails()
    assert len(triaged) >= 2

    top_item = triaged[0]
    assert top_item["category"] == "FINANCIAL"
    assert top_item["urgency"] == "HIGH"
    assert top_item["recommended_action"] == "REPLY_URGENT"


def test_email_draft_with_governance_approval():
    msg = MockEmailMessage.objects.create(
        source="email_readonly",
        external_event_id="msg-draft-1",
        sender="partner@venture.com",
        subject="Follow up on Partnership Proposal",
        body="Could you let us know if you are open to discussing integration terms?",
        classification=MockEmailMessage.Classification.INFORMATION,
        proposed_action={"action": "reply"},
        rule_decision="ALLOW",
    )

    result = EmailTriageAndDraftEngine.generate_draft_response(
        message_id=msg.id,
        request_approval=True,
        actor_id="test_ea",
    )

    assert result["no_external_send"] is True
    assert result["review_status"] == ExecutiveEmailDraft.ReviewStatus.NEEDS_REVIEW
    assert result["approval_id"] is not None

    approval = ApprovalRequest.objects.get(id=result["approval_id"])
    assert approval.action == "executive_assistant.email.send_external"
    assert approval.status == ApprovalRequest.Status.PENDING

    # Check AuditEvent
    audit = AuditEvent.objects.filter(object_id=result["draft_id"]).first()
    assert audit is not None
    assert audit.action == "executive_assistant.email.draft_generated"


# ==============================================================================
# 3. Morning Executive Brief Engine Tests
# ==============================================================================

def test_morning_brief_generation(active_objective):
    today = timezone.now().date()
    brief_data = MorningExecutiveBriefEngine.generate_morning_brief(
        target_date=today,
        actor_id="executive_assistant",
    )

    assert brief_data["brief_id"] is not None
    assert "Morning Briefing" in brief_data["title"]
    assert "agenda_items" in brief_data
    assert "urgent_inbox" in brief_data
    assert len(brief_data["active_objectives"]) >= 1

    stored_brief = ExecutiveBrief.objects.get(id=brief_data["brief_id"])
    assert stored_brief.brief_type == ExecutiveBrief.BriefType.MORNING_BRIEF
    assert stored_brief.no_external_send is True


# ==============================================================================
# 4. Delegation & Follow-Up Tracker Tests
# ==============================================================================

def test_delegation_tracker_and_nudge(active_objective):
    task = Task.objects.create(
        objective=active_objective,
        title="Setup Stripe Production Webhook",
        status=Task.Status.IN_PROGRESS,
        created_by="ceo",
    )

    # 1. Create Delegation overdue
    past_due = timezone.now() - timedelta(hours=2)
    delegation = DelegationTrackerEngine.create_delegation(
        task_id=task.id,
        delegated_to="developer_agent",
        due_at=past_due,
        title="Deploy Stripe Webhook",
        notes="High priority for launch.",
    )

    # 2. Status verification
    report = DelegationTrackerEngine.get_delegations_report()
    assert report["overdue_count"] >= 1
    delegation.refresh_from_db()
    assert delegation.status == DelegatedTaskFollowUp.Status.OVERDUE

    # 3. Nudge
    nudge_res = DelegationTrackerEngine.nudge_delegation(
        delegation_id=delegation.id,
        nudge_note="CEO requesting status update for board deck.",
        actor_id="ea_agent",
    )

    assert nudge_res["nudge_count"] == 1
    assert "CEO requesting status update" in nudge_res["notes"]
    delegation.refresh_from_db()
    assert delegation.nudge_count == 1
    assert delegation.last_nudged_at is not None

    # Check AuditEvent
    audit = AuditEvent.objects.filter(object_id=str(delegation.id)).first()
    assert audit is not None
    assert audit.action == "executive_assistant.delegation.nudged"


# ==============================================================================
# 5. REST API & UI Integration Tests
# ==============================================================================

def test_api_calendar_conflicts_and_reschedule(client):
    now = timezone.now()
    e = ExecutiveCalendarEvent.objects.create(
        external_event_id="api-cal-1",
        title="Weekly Sync",
        starts_at=now + timedelta(days=1),
        ends_at=now + timedelta(days=1, minutes=30),
        created_by="test_user",
    )

    # GET conflicts
    res_conf = client.get("/api/v1/executive-assistant/calendar/conflicts/")
    assert res_conf.status_code == 200
    assert "conflicts" in res_conf.json()

    # POST reschedule proposal
    res_prop = client.post(
        "/api/v1/executive-assistant/calendar/reschedule-proposal/",
        data=json.dumps({"event_id": str(e.id), "search_days": 3}),
        content_type="application/json",
    )
    assert res_prop.status_code == 200
    assert "reschedule_proposal" in res_prop.json()


def test_api_email_triage_and_draft(client):
    msg = MockEmailMessage.objects.create(
        source="email_readonly",
        external_event_id="api-msg-1",
        sender="client@acme.com",
        subject="Project Alpha Question",
        body="Can we review the roadmap tomorrow?",
        classification=MockEmailMessage.Classification.INFORMATION,
        proposed_action={"action": "reply"},
        rule_decision="ALLOW",
    )

    # GET triage
    res_triage = client.get("/api/v1/executive-assistant/email/triage/")
    assert res_triage.status_code == 200
    assert res_triage.json()["total_count"] >= 1

    # POST draft
    res_draft = client.post(
        "/api/v1/executive-assistant/email/draft/",
        data=json.dumps({"message_id": str(msg.id), "request_approval": True}),
        content_type="application/json",
        **headers("ea-draft-api-1"),
    )
    assert res_draft.status_code == 201
    assert "draft_result" in res_draft.json()


def test_api_morning_brief_and_dashboard_page(client, test_user, active_objective):
    # GET morning brief API
    res_brief = client.get("/api/v1/executive-assistant/brief/morning/")
    assert res_brief.status_code == 200
    assert "agenda_items" in res_brief.json()

    # GET HTML Morning Brief Page
    client.force_login(test_user)
    res_page = client.get("/executive-assistant/morning-brief/")
    assert res_page.status_code == 200
    html = res_page.content.decode("utf-8")
    assert "CEO Morning Briefing" in html
    assert "Executive Daily Digest" in html
    assert "Today's Calendar Schedule" in html


def test_api_delegations_lifecycle(client, active_objective):
    task = Task.objects.create(
        objective=active_objective,
        title="Setup Sentry Alerting",
        status=Task.Status.ASSIGNED,
        created_by="ceo",
    )
    due = (timezone.now() + timedelta(days=2)).isoformat()

    # 1. POST create delegation
    res_create = client.post(
        "/api/v1/executive-assistant/delegations/create/",
        data=json.dumps({
            "task_id": str(task.id),
            "delegated_to": "devops_agent",
            "due_at": due,
            "title": "Configure Sentry Alerts",
        }),
        content_type="application/json",
    )
    assert res_create.status_code == 201
    delegation_id = res_create.json()["delegation"]["id"]

    # 2. GET report
    res_rep = client.get("/api/v1/executive-assistant/delegations/")
    assert res_rep.status_code == 200
    assert res_rep.json()["total_count"] >= 1

    # 3. POST nudge
    res_nudge = client.post(
        f"/api/v1/executive-assistant/delegations/{delegation_id}/nudge/",
        data=json.dumps({"nudge_note": "Friendly reminder: please configure Slack webhook too."}),
        content_type="application/json",
        HTTP_X_ACTOR_ID="ea_test",
    )
    assert res_nudge.status_code == 200
    assert res_nudge.json()["nudge_result"]["nudge_count"] == 1
