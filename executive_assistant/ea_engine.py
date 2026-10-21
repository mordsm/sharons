"""
Executive Assistant Advanced Operational Engine for 'sharons'.

Provides:
1. CalendarConflictEngine: Overlap & buffer conflict detection + intelligent rescheduling proposals.
2. EmailTriageAndDraftEngine: Urgency/category triage + executive draft response with governance gates.
3. MorningExecutiveBriefEngine: Automated 360-degree morning brief generation.
4. DelegationTrackerEngine: SLA tracking, risk detection, and automated follow-up nudges for delegated tasks.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.services import canonical_hash
from governance.models import ApprovalRequest, AuditEvent
from mailbox.models import MockEmailMessage
from operations.models import Task
from portfolio.models import Objective
from executive_assistant.models import (
    DelegatedTaskFollowUp,
    ExecutiveBrief,
    ExecutiveBriefTaskProposal,
    ExecutiveCalendarEvent,
    ExecutiveEmailDraft,
)


# ==============================================================================
# 1. Calendar Conflict & Reschedule Engine
# ==============================================================================

class CalendarConflictEngine:
    """
    Detects scheduling conflicts (direct overlaps, buffer violations)
    and computes available reschedule slots within executive working hours.
    """

    WORK_START_HOUR = 9   # 09:00
    WORK_END_HOUR = 18    # 18:00
    DEFAULT_BUFFER_MINUTES = 15

    @classmethod
    def detect_conflicts(
        cls,
        events: list[ExecutiveCalendarEvent] | None = None,
        min_buffer_minutes: int = DEFAULT_BUFFER_MINUTES,
    ) -> list[dict[str, Any]]:
        """
        Scans calendar events for overlaps and buffer violations.
        """
        if events is None:
            # Check all confirmed or tentative events from now - 1 day onwards
            cutoff = timezone.now() - timedelta(days=1)
            events = list(
                ExecutiveCalendarEvent.objects.filter(
                    starts_at__gte=cutoff,
                    status__in=[
                        ExecutiveCalendarEvent.Status.CONFIRMED,
                        ExecutiveCalendarEvent.Status.TENTATIVE,
                    ],
                ).order_by("starts_at")
            )
        else:
            events = sorted(events, key=lambda e: e.starts_at)

        conflicts: list[dict[str, Any]] = []

        for i in range(len(events)):
            e1 = events[i]
            for j in range(i + 1, len(events)):
                e2 = events[j]

                # If e2 starts after e1 ends + buffer, no conflict with subsequent events on this day
                if e2.starts_at >= e1.ends_at + timedelta(minutes=min_buffer_minutes):
                    # Since list is sorted by starts_at, later events will also start after this
                    if e2.starts_at.date() > e1.ends_at.date():
                        break

                # 1. Direct Overlap
                if e2.starts_at < e1.ends_at:
                    overlap_duration = min(e1.ends_at, e2.ends_at) - max(e1.starts_at, e2.starts_at)
                    overlap_minutes = int(overlap_duration.total_seconds() / 60)
                    conflicts.append({
                        "conflict_type": "OVERLAP",
                        "severity": "HIGH",
                        "event_1": {
                            "id": str(e1.id),
                            "title": e1.title,
                            "starts_at": e1.starts_at.isoformat(),
                            "ends_at": e1.ends_at.isoformat(),
                            "organizer": e1.organizer,
                        },
                        "event_2": {
                            "id": str(e2.id),
                            "title": e2.title,
                            "starts_at": e2.starts_at.isoformat(),
                            "ends_at": e2.ends_at.isoformat(),
                            "organizer": e2.organizer,
                        },
                        "overlap_minutes": overlap_minutes,
                        "description": f"Direct conflict: '{e1.title}' overlaps with '{e2.title}' by {overlap_minutes} minutes.",
                    })
                # 2. Buffer Violation (Back-to-back without sufficient transition buffer)
                elif e2.starts_at < e1.ends_at + timedelta(minutes=min_buffer_minutes):
                    buffer_available = int((e2.starts_at - e1.ends_at).total_seconds() / 60)
                    conflicts.append({
                        "conflict_type": "BUFFER_VIOLATION",
                        "severity": "MEDIUM",
                        "event_1": {
                            "id": str(e1.id),
                            "title": e1.title,
                            "starts_at": e1.starts_at.isoformat(),
                            "ends_at": e1.ends_at.isoformat(),
                            "organizer": e1.organizer,
                        },
                        "event_2": {
                            "id": str(e2.id),
                            "title": e2.title,
                            "starts_at": e2.starts_at.isoformat(),
                            "ends_at": e2.ends_at.isoformat(),
                            "organizer": e2.organizer,
                        },
                        "buffer_available_minutes": buffer_available,
                        "min_required_minutes": min_buffer_minutes,
                        "description": (
                            f"Buffer violation: Only {buffer_available} min between '{e1.title}' "
                            f"and '{e2.title}' (required: {min_buffer_minutes} min)."
                        ),
                    })

        return conflicts

    @classmethod
    def suggest_reschedule(
        cls,
        event_id: str | uuid.UUID,
        search_days: int = 5,
        slot_duration_minutes: int | None = None,
    ) -> dict[str, Any]:
        """
        Finds free slots in the executive's calendar to reschedule a conflicting event.
        """
        event = ExecutiveCalendarEvent.objects.get(id=event_id)
        duration = event.ends_at - event.starts_at
        if slot_duration_minutes:
            duration = timedelta(minutes=slot_duration_minutes)

        start_date = event.starts_at.date()
        tz = timezone.get_current_timezone()

        # Query all existing events across search window
        window_end = timezone.make_aware(datetime.combine(start_date + timedelta(days=search_days), time(cls.WORK_END_HOUR, 0)), tz)
        window_start = timezone.make_aware(datetime.combine(start_date, time(cls.WORK_START_HOUR, 0)), tz)

        existing_events = list(
            ExecutiveCalendarEvent.objects.filter(
                starts_at__lt=window_end,
                ends_at__gt=window_start,
                status__in=[ExecutiveCalendarEvent.Status.CONFIRMED, ExecutiveCalendarEvent.Status.TENTATIVE],
            ).exclude(id=event.id).order_by("starts_at")
        )

        candidate_slots: list[dict[str, Any]] = []

        for d in range(search_days):
            current_day = start_date + timedelta(days=d)
            # Skip weekends (Saturday=5, Sunday=6)
            if current_day.weekday() >= 5:
                continue

            day_work_start = timezone.make_aware(datetime.combine(current_day, time(cls.WORK_START_HOUR, 0)), tz)
            day_work_end = timezone.make_aware(datetime.combine(current_day, time(cls.WORK_END_HOUR, 0)), tz)

            # Events on current day
            day_events = [
                e for e in existing_events
                if e.starts_at < day_work_end and e.ends_at > day_work_start
            ]

            # Iterate in 30-min steps to find a clean slot
            curr_cursor = day_work_start
            buffer = timedelta(minutes=cls.DEFAULT_BUFFER_MINUTES)

            while curr_cursor + duration <= day_work_end:
                proposed_start = curr_cursor
                proposed_end = curr_cursor + duration

                # Check if this slot collides with any event + buffer
                collision = False
                for de in day_events:
                    # Collides if starts before de.ends_at + buffer and ends after de.starts_at - buffer
                    if proposed_start < (de.ends_at + buffer) and proposed_end > (de.starts_at - buffer):
                        collision = True
                        break

                if not collision:
                    candidate_slots.append({
                        "starts_at": proposed_start.isoformat(),
                        "ends_at": proposed_end.isoformat(),
                        "date": current_day.isoformat(),
                        "duration_minutes": int(duration.total_seconds() / 60),
                        "confidence_score": 95 if d <= 1 else max(70, 95 - d * 5),
                        "rationale": f"Free window on {current_day.strftime('%A, %b %d')} with full 15-min buffers.",
                    })
                    if len(candidate_slots) >= 3:
                        break

                curr_cursor += timedelta(minutes=30)

            if len(candidate_slots) >= 3:
                break

        return {
            "target_event": {
                "id": str(event.id),
                "title": event.title,
                "current_starts_at": event.starts_at.isoformat(),
                "current_ends_at": event.ends_at.isoformat(),
            },
            "candidate_slots": candidate_slots,
            "recommended_slot": candidate_slots[0] if candidate_slots else None,
        }


# ==============================================================================
# 2. Email Triage & Draft Response Engine
# ==============================================================================

class EmailTriageAndDraftEngine:
    """
    Analyzes incoming read-only emails, tags urgency and category,
    and generates draft responses bound by Governance approval rules.
    """

    URGENT_KEYWORDS = {"urgent", "asap", "immediately", "critical", "down", "outage", "emergency", "breach"}
    FINANCIAL_KEYWORDS = {"invoice", "payment", "billing", "budget", "pricing", "wire", "receipt", "arr", "revenue"}
    LEGAL_KEYWORDS = {"contract", "nda", "terms", "agreement", "liability", "dpa", "gdpr", "compliance", "lawyer"}
    STRATEGIC_KEYWORDS = {"investor", "board", "partnership", "acquisition", "round", "equity", "shareholder"}
    OPERATIONAL_KEYWORDS = {"deployment", "server", "cluster", "bug", "release", "incident", "jira", "ci/cd"}

    @classmethod
    def triage_emails(cls, limit: int = 50) -> list[dict[str, Any]]:
        """
        Triages unread/recent MockEmailMessages with heuristic scoring.
        """
        emails = MockEmailMessage.objects.all().order_by("-created_at")[:limit]
        triaged_list = []

        for msg in emails:
            content = f"{msg.subject} {msg.body}".lower()

            # 1. Category Classification
            category = "INFORMATIONAL"
            if any(k in content for k in cls.FINANCIAL_KEYWORDS):
                category = "FINANCIAL"
            elif any(k in content for k in cls.LEGAL_KEYWORDS):
                category = "LEGAL"
            elif any(k in content for k in cls.STRATEGIC_KEYWORDS):
                category = "STRATEGIC"
            elif any(k in content for k in cls.OPERATIONAL_KEYWORDS):
                category = "OPERATIONAL"

            # 2. Urgency Classification
            urgency = "LOW"
            if any(k in content for k in cls.URGENT_KEYWORDS) or category in ["LEGAL", "FINANCIAL"]:
                if any(k in content for k in cls.URGENT_KEYWORDS):
                    urgency = "HIGH"
                else:
                    urgency = "MEDIUM"
            elif category == "STRATEGIC":
                urgency = "MEDIUM"

            # 3. Recommended Action
            action = "FYI_ONLY"
            if urgency == "HIGH":
                action = "REPLY_URGENT"
            elif category in ["FINANCIAL", "LEGAL"]:
                action = "APPROVAL_REQUIRED"
            elif "?" in msg.body or "please" in content or "could you" in content:
                action = "REPLY_NEEDED"

            triaged_list.append({
                "message_id": str(msg.id),
                "sender": msg.sender,
                "subject": msg.subject,
                "preview": msg.body[:140] + ("..." if len(msg.body) > 140 else ""),
                "received_at": msg.created_at.isoformat(),
                "category": category,
                "urgency": urgency,
                "recommended_action": action,
            })

        # Sort: HIGH urgency first, then MEDIUM, then LOW
        urgency_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        triaged_list.sort(key=lambda x: (urgency_rank.get(x["urgency"], 3), x["received_at"]))
        return triaged_list

    @classmethod
    def generate_draft_response(
        cls,
        message_id: str | uuid.UUID,
        request_approval: bool = True,
        actor_id: str = "executive_assistant",
        correlation_id: str = "",
    ) -> dict[str, Any]:
        """
        Creates an executive reply draft and optionally lodges a Governance ApprovalRequest.
        """
        msg = MockEmailMessage.objects.get(id=message_id)

        # Generate contextual executive response
        subject = msg.subject if msg.subject.lower().startswith("re:") else f"Re: {msg.subject}"
        body = (
            f"Hi {msg.sender.split('@')[0].capitalize()},\n\n"
            f"Thank you for your message regarding '{msg.subject}'.\n\n"
            "I have reviewed the details and will follow up shortly with our complete operating position.\n\n"
            "Best regards,\n"
            "Sharon Moshe\nExecutive Office"
        )
        rationale = f"Automated executive acknowledgment for message from {msg.sender} with category triage."

        with transaction.atomic():
            draft = ExecutiveEmailDraft.objects.create(
                source_message_id=msg.id,
                draft_type=ExecutiveEmailDraft.DraftType.REPLY,
                to_recipients=[msg.sender],
                cc_recipients=[],
                subject=subject,
                body=body,
                rationale=rationale,
                review_status=ExecutiveEmailDraft.ReviewStatus.NEEDS_REVIEW,
                no_external_send=True,
                created_by=actor_id,
            )

            approval_record = None
            if request_approval:
                action_payload = {
                    "draft_id": str(draft.id),
                    "to": draft.to_recipients,
                    "subject": draft.subject,
                    "preview": draft.body[:120],
                }
                approval_record = ApprovalRequest.objects.create(
                    subject_type="executive_assistant.ExecutiveEmailDraft",
                    subject_id=str(draft.id),
                    subject_version=1,
                    action="executive_assistant.email.send_external",
                    action_payload=action_payload,
                    action_payload_hash=canonical_hash(action_payload),
                    requested_by=actor_id,
                    status=ApprovalRequest.Status.PENDING,
                    expires_at=timezone.now() + timedelta(days=2),
                )

            AuditEvent.objects.create(
                actor_type=AuditEvent.ActorType.AGENT,
                actor_id=actor_id,
                action="executive_assistant.email.draft_generated",
                object_type="executive_assistant.ExecutiveEmailDraft",
                object_id=str(draft.id),
                correlation_id=correlation_id or str(uuid.uuid4()),
                metadata={
                    "message_id": str(msg.id),
                    "sender": msg.sender,
                    "approval_requested": request_approval,
                    "approval_id": str(approval_record.id) if approval_record else None,
                },
            )

        return {
            "draft_id": str(draft.id),
            "source_message_id": str(msg.id),
            "to": draft.to_recipients,
            "subject": draft.subject,
            "body": draft.body,
            "review_status": draft.review_status,
            "approval_id": str(approval_record.id) if approval_record else None,
            "no_external_send": draft.no_external_send,
        }


# ==============================================================================
# 3. Morning Executive Brief Engine
# ==============================================================================

class MorningExecutiveBriefEngine:
    """
    Compiles daily 360-degree morning brief for the CEO:
    - Today's calendar + conflicts
    - High-urgency triage items
    - Decisions awaiting CEO signoff
    - At-risk or overdue delegations
    - CoS Active Objectives status
    """

    @classmethod
    def generate_morning_brief(
        cls,
        target_date = None,
        actor_id: str = "executive_assistant",
    ) -> dict[str, Any]:
        now = timezone.now()
        target_date = target_date or now.date()

        day_start = timezone.make_aware(datetime.combine(target_date, time.min))
        day_end = timezone.make_aware(datetime.combine(target_date, time.max))

        # 1. Today's Calendar & Conflicts
        events = list(
            ExecutiveCalendarEvent.objects.filter(
                starts_at__gte=day_start,
                starts_at__lte=day_end,
                status__in=[ExecutiveCalendarEvent.Status.CONFIRMED, ExecutiveCalendarEvent.Status.TENTATIVE],
            ).order_by("starts_at")
        )
        conflicts = CalendarConflictEngine.detect_conflicts(events)

        # 2. Urgent Inbox Items
        triaged = EmailTriageAndDraftEngine.triage_emails(limit=15)
        urgent_inbox = [m for m in triaged if m["urgency"] in ["HIGH", "MEDIUM"]]

        # 3. Pending Governance Decisions
        pending_approvals = list(
            ApprovalRequest.objects.filter(
                status=ApprovalRequest.Status.PENDING,
                expires_at__gte=now,
            ).order_by("expires_at")[:5]
        )

        # 4. Delegations at risk
        delegation_report = DelegationTrackerEngine.get_delegations_report()
        urgent_delegations = delegation_report["at_risk"] + delegation_report["overdue"]

        # 5. CoS Strategic Summary
        active_objectives = list(Objective.objects.filter(status=Objective.Status.ACTIVE)[:3])

        # Synthesize brief summary
        summary_lines = [
            f"Good morning, Sharon. Here is your executive briefing for {target_date.strftime('%A, %B %d, %Y')}:",
            f"- **Schedule**: {len(events)} events scheduled today ({len(conflicts)} scheduling conflicts detected).",
            f"- **Executive Decisions**: {len(pending_approvals)} decisions awaiting your review/approval.",
            f"- **Inbox Triage**: {len(urgent_inbox)} high/medium priority messages requiring awareness.",
            f"- **Delegated Tasks**: {len(urgent_delegations)} items require follow-up ({len(delegation_report['overdue'])} overdue).",
            f"- **Strategic Focus**: {len(active_objectives)} active 90-day objectives in flight.",
        ]
        summary_text = "\n".join(summary_lines)

        agenda_items = [
            {
                "time": f"{e.starts_at.strftime('%H:%M')} - {e.ends_at.strftime('%H:%M')}",
                "title": e.title,
                "location": e.location or "Virtual / Google Meet",
                "organizer": e.organizer,
                "has_conflict": any(c["event_1"]["id"] == str(e.id) or c["event_2"]["id"] == str(e.id) for c in conflicts),
            }
            for e in events
        ]

        decisions_needed = [
            {
                "approval_id": str(app.id),
                "action": app.action,
                "requested_by": app.requested_by,
                "expires_at": app.expires_at.isoformat(),
            }
            for app in pending_approvals
        ]

        follow_ups = [
            {
                "delegation_id": d["id"],
                "title": d["title"],
                "delegated_to": d["delegated_to"],
                "status": d["status"],
                "due_at": d["due_at"],
            }
            for d in urgent_delegations
        ]

        # Store in ExecutiveBrief
        with transaction.atomic():
            brief = ExecutiveBrief.objects.create(
                brief_type=ExecutiveBrief.BriefType.MORNING_BRIEF,
                title=f"Morning Briefing - {target_date.strftime('%Y-%m-%d')}",
                source_window={
                    "start": day_start.isoformat(),
                    "end": day_end.isoformat(),
                    "target_date": target_date.isoformat(),
                },
                summary=summary_text,
                agenda_items=agenda_items,
                follow_ups=follow_ups,
                decisions_needed=decisions_needed,
                inbox_items=urgent_inbox,
                status=ExecutiveBrief.Status.READY,
                no_external_send=True,
                created_by=actor_id,
            )

        return {
            "brief_id": str(brief.id),
            "title": brief.title,
            "target_date": target_date.isoformat(),
            "summary": brief.summary,
            "agenda_items": brief.agenda_items,
            "conflicts_detected": conflicts,
            "decisions_needed": brief.decisions_needed,
            "urgent_inbox": brief.inbox_items,
            "urgent_delegations": brief.follow_ups,
            "active_objectives": [
                {"id": str(obj.id), "title": obj.name, "owner": obj.owner_agent_id}
                for obj in active_objectives
            ],
            "created_at": brief.created_at.isoformat(),
        }


# ==============================================================================
# 4. Delegation & Follow-Up Engine
# ==============================================================================

class DelegationTrackerEngine:
    """
    Manages delegated task commitments, detects SLA slippage,
    and handles automated follow-up nudges with audit logging.
    """

    @classmethod
    def create_delegation(
        cls,
        task_id: str | uuid.UUID,
        delegated_to: str,
        due_at: datetime,
        title: str = "",
        notes: str = "",
        delegated_by: str = "ceo",
    ) -> DelegatedTaskFollowUp:
        task = Task.objects.get(id=task_id)
        if not title:
            title = task.title

        return DelegatedTaskFollowUp.objects.create(
            task=task,
            delegated_to=delegated_to,
            delegated_by=delegated_by,
            title=title,
            due_at=due_at,
            status=DelegatedTaskFollowUp.Status.PENDING,
            notes=notes,
        )

    @classmethod
    def get_delegations_report(cls) -> dict[str, Any]:
        """
        Calculates live SLA status for all active delegations.
        """
        now = timezone.now()
        delegations = list(DelegatedTaskFollowUp.objects.select_related("task").all())

        on_track = []
        at_risk = []
        overdue = []
        completed = []

        for d in delegations:
            # Refresh status dynamically
            if d.task.status in [Task.Status.COMPLETED, Task.Status.CANCELLED]:
                new_status = DelegatedTaskFollowUp.Status.COMPLETED
            elif d.due_at < now:
                new_status = DelegatedTaskFollowUp.Status.OVERDUE
            elif d.due_at - now <= timedelta(hours=24):
                new_status = DelegatedTaskFollowUp.Status.AT_RISK
            else:
                new_status = DelegatedTaskFollowUp.Status.ON_TRACK

            if d.status != new_status:
                d.status = new_status
                d.save(update_fields=["status", "updated_at"])

            item_dict = {
                "id": str(d.id),
                "task_id": str(d.task_id),
                "title": d.title,
                "delegated_to": d.delegated_to,
                "delegated_by": d.delegated_by,
                "due_at": d.due_at.isoformat(),
                "status": d.status,
                "nudge_count": d.nudge_count,
                "last_nudged_at": d.last_nudged_at.isoformat() if d.last_nudged_at else None,
                "notes": d.notes,
            }

            if d.status == DelegatedTaskFollowUp.Status.COMPLETED:
                completed.append(item_dict)
            elif d.status == DelegatedTaskFollowUp.Status.OVERDUE:
                overdue.append(item_dict)
            elif d.status == DelegatedTaskFollowUp.Status.AT_RISK:
                at_risk.append(item_dict)
            else:
                on_track.append(item_dict)

        return {
            "total_count": len(delegations),
            "overdue_count": len(overdue),
            "at_risk_count": len(at_risk),
            "on_track_count": len(on_track),
            "completed_count": len(completed),
            "overdue": overdue,
            "at_risk": at_risk,
            "on_track": on_track,
            "completed": completed,
        }

    @classmethod
    def nudge_delegation(
        cls,
        delegation_id: str | uuid.UUID,
        nudge_note: str = "",
        actor_id: str = "executive_assistant",
        correlation_id: str = "",
    ) -> dict[str, Any]:
        """
        Nudges an assignee regarding a delegated task and records audit trail.
        """
        delegation = DelegatedTaskFollowUp.objects.get(id=delegation_id)
        now = timezone.now()

        delegation.nudge_count += 1
        delegation.last_nudged_at = now
        if nudge_note:
            note_entry = f"[{now.strftime('%Y-%m-%d %H:%M')}] Nudge #{delegation.nudge_count}: {nudge_note}"
            delegation.notes = f"{delegation.notes}\n{note_entry}".strip()
        delegation.save(update_fields=["nudge_count", "last_nudged_at", "notes", "updated_at"])

        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.AGENT,
            actor_id=actor_id,
            action="executive_assistant.delegation.nudged",
            object_type="executive_assistant.DelegatedTaskFollowUp",
            object_id=str(delegation.id),
            correlation_id=correlation_id or str(uuid.uuid4()),
            metadata={
                "delegated_to": delegation.delegated_to,
                "nudge_count": delegation.nudge_count,
                "task_title": delegation.title,
                "due_at": delegation.due_at.isoformat(),
            },
        )

        return {
            "id": str(delegation.id),
            "task_id": str(delegation.task_id),
            "title": delegation.title,
            "delegated_to": delegation.delegated_to,
            "nudge_count": delegation.nudge_count,
            "last_nudged_at": delegation.last_nudged_at.isoformat(),
            "status": delegation.status,
            "notes": delegation.notes,
        }
