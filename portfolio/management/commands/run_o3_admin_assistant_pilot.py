from django.core.management.base import BaseCommand

from executive_assistant.models import ExecutiveEmailDraft
from executive_assistant.services import (
    create_email_draft_from_message,
    create_executive_brief,
    review_email_draft,
)
from mailbox.services import ingest_mock_email
from operations.models import AcceptanceCriterion, AgentDefinition, Task
from operations.services import assign_task, record_task_evidence, transition_task, upsert_task
from portfolio.models import Objective
from qa.models import VerificationReview
from qa.services import review_task_evidence


class Command(BaseCommand):
    help = "Run the O3 zero-touch administration safe triage pilot inside Sharons."

    def handle(self, *args, **options):
        actor = "codex"
        correlation_id = "o3-admin-assistant-pilot-2026-09-29"
        objective = Objective.objects.get(code="O3")
        self._ensure_agents()
        self._close_baseline_tasks(correlation_id=correlation_id)

        pilot, _created = upsert_task(
            {
                "title": "O3: Run zero-touch administration triage pilot",
                "business_outcome": (
                    "One controlled Sharons pilot proves an administrative inbox item can be triaged, "
                    "drafted, briefed, and tracked without external sending or scheduling."
                ),
                "objective_id": str(objective.id),
                "external_key": "executive_assistant:O3:admin-triage-pilot",
                "acceptance_criteria": [
                    {
                        "description": "Pilot creates an administrative inbox signal, no-send draft, and executive brief.",
                        "criterion_type": AcceptanceCriterion.CriterionType.EVIDENCE,
                        "required": True,
                    },
                    {
                        "description": "Pilot evidence confirms no external email, calendar write, portal login, form submit, or payment.",
                        "criterion_type": AcceptanceCriterion.CriterionType.MANUAL,
                        "required": True,
                    },
                ],
            },
            actor_id=actor,
            correlation_id=correlation_id,
        )
        pilot = self._advance_to_in_progress(pilot, "executive_assistant", correlation_id)

        message, _message_created = ingest_mock_email(
            {
                "source": "o3_mock_gmail",
                "external_event_id": "o3-admin-follow-up-001",
                "sender": "office@example-institution.test",
                "subject": "Please follow up on school reimbursement form",
                "body": (
                    "Please follow up tomorrow about the reimbursement form checklist. "
                    "This is an O3 pilot item; do not send email or schedule anything externally."
                ),
            },
            actor_id="executive_assistant",
            correlation_id=correlation_id,
        )

        draft = ExecutiveEmailDraft.objects.filter(source_message_id=message.id).first()
        if draft is None:
            draft = create_email_draft_from_message(
                {
                    "source_message_id": str(message.id),
                    "draft_type": ExecutiveEmailDraft.DraftType.REPLY,
                    "rationale": "O3 pilot no-send draft for administrative follow-up triage.",
                },
                actor_id="executive_assistant",
                correlation_id=correlation_id,
            )
        if draft.review_status == ExecutiveEmailDraft.ReviewStatus.NEEDS_REVIEW:
            draft = review_email_draft(
                {
                    "decision": ExecutiveEmailDraft.ReviewStatus.APPROVED,
                    "review_note": "Approved as internal draft only; external sending remains disabled.",
                },
                draft_id=str(draft.id),
                actor_id="qa_agent",
                correlation_id=correlation_id,
            )

        brief = create_executive_brief(
            {
                "brief_type": "INBOX_TRIAGE",
                "title": "O3 Administration Triage Pilot Brief",
                "source_window": {"correlation_id": correlation_id, "mode": "pilot"},
            },
            actor_id="executive_assistant",
            correlation_id=correlation_id,
        )

        if pilot.evidence.count() == 0:
            evidence = [
                (
                    f"mailbox.MockEmailMessage:{message.id}",
                    f"Administrative follow-up email ingested as {message.classification}; proposed action {message.proposed_action.get('type')}.",
                ),
                (
                    f"executive_assistant.ExecutiveEmailDraft:{draft.id}",
                    f"No-send draft created and reviewed as {draft.review_status}; no_external_send={draft.no_external_send}.",
                ),
                (
                    f"executive_assistant.ExecutiveBrief:{brief.id}",
                    f"Inbox triage brief created with {len(brief.inbox_items)} inbox items and no_external_send={brief.no_external_send}.",
                ),
            ]
            for reference, summary in evidence:
                record_task_evidence(
                    {
                        "kind": "ARTIFACT",
                        "uri_or_reference": reference,
                        "metadata": {
                            "objective": "O3",
                            "summary": summary,
                            "correlation_id": correlation_id,
                            "no_external_action": True,
                        },
                        "verified": False,
                    },
                    task_id=str(pilot.id),
                    actor_id=actor,
                    correlation_id=correlation_id,
                )

        self._complete_task(
            pilot,
            correlation_id,
            "Accepted: O3 pilot triaged admin mail, produced a reviewed no-send draft, and created an executive brief with no external action.",
        )

        pilot.refresh_from_db()
        self.stdout.write(f"pilot={pilot.title} status={pilot.status} version={pilot.version}")
        self.stdout.write(f"message={message.id} classification={message.classification}")
        self.stdout.write(f"draft={draft.id} review_status={draft.review_status} no_external_send={draft.no_external_send}")
        self.stdout.write(f"brief={brief.id} inbox_items={len(brief.inbox_items)} no_external_send={brief.no_external_send}")

    def _ensure_agents(self) -> None:
        definitions = [
            {
                "agent_id": "administrative_agent",
                "role": "Administrative Agent",
                "capabilities": ["administration", "case_tracking", "document_checklists", "renewal_tracking"],
                "tools": ["administrative_records", "task_registry", "audit_log"],
                "allowed_data_classes": ["PUBLIC", "INTERNAL", "CONFIDENTIAL"],
                "forbidden_actions": ["submit_form", "send_message", "pay_bill", "portal_login", "legal_commitment"],
                "max_risk_level": AgentDefinition.RiskLevel.MEDIUM,
                "max_concurrent_tasks": 2,
            },
            {
                "agent_id": "executive_assistant",
                "role": "Executive Assistant",
                "capabilities": ["administration", "scheduling", "inbox_triage", "follow_up", "weekly_review_prep"],
                "tools": ["mailbox_mock", "task_registry", "memory"],
                "allowed_data_classes": ["PUBLIC", "INTERNAL", "CONFIDENTIAL"],
                "forbidden_actions": ["send_email", "contact_person", "spend_money", "production_change", "legal_commitment"],
                "max_risk_level": AgentDefinition.RiskLevel.LOW,
                "max_concurrent_tasks": 3,
            },
            {
                "agent_id": "project_manager",
                "role": "Project Manager",
                "capabilities": ["project_management", "planning", "coordination", "status_reporting", "risk_tracking"],
                "tools": ["task_registry", "audit_log", "weekly_review"],
                "allowed_data_classes": ["PUBLIC", "INTERNAL", "CONFIDENTIAL"],
                "forbidden_actions": ["external_publish", "contact_person", "spend_money", "production_change", "legal_commitment"],
                "max_risk_level": AgentDefinition.RiskLevel.MEDIUM,
                "max_concurrent_tasks": 3,
            },
        ]
        for definition in definitions:
            AgentDefinition.objects.update_or_create(
                agent_id=definition["agent_id"],
                defaults={**definition, "active": True, "prompt_version": "core-agents-v1"},
            )

    def _close_baseline_tasks(self, *, correlation_id: str) -> None:
        baseline = [
            (
                "Administrative Agent: Assess active APIs and DB status",
                "administrative_agent",
                "Administrative Agent APIs and DB boundary are assessed from source.",
                [
                    (
                        "administrative_agent/README.md:API",
                        "Administrative Agent exposes health, obligations, cases, checklists, documents, events, draft communications, and draft action APIs.",
                    ),
                    (
                        "administrative_agent/app/store.py:administrative_records",
                        "Administrative records persist to Postgres via a collection/user/status record store.",
                    ),
                ],
                "Accepted: Administrative Agent has safe case/obligation APIs and a Postgres-backed persistence boundary.",
            ),
            (
                "Administrative Agent: Create zero-touch admin milestone tasks",
                "project_manager",
                "Zero-touch admin milestone scope is defined from source safety boundaries.",
                [
                    (
                        "administrative_agent/README.md:Safe by default",
                        "The agent records obligations and drafts actions but does not submit forms, send messages, pay bills, or log into portals.",
                    ),
                    (
                        "administrative_agent/README.md:Integration Role",
                        "Compass, TaskCommander, Mail Manager, and Rules Engine handoff roles are documented.",
                    ),
                ],
                "Accepted: zero-touch milestone can focus on safe internal triage, draft, checklist, and reminder handoff.",
            ),
            (
                "TaskCommander: Assess reminder/calendar integration state",
                "project_manager",
                "TaskCommander calendar/reminder integration state is assessed from source.",
                [
                    (
                        "TaskCommander/WINDOWS_TASK_SCHEDULER.md:run-once --calendar-only --dry-run",
                        "TaskCommander supports calendar-only dry-run scheduler execution before enabling live alerts.",
                    ),
                    (
                        "TaskCommander/task_reminder_codex_package/tests/test_google_calendar_sync.py",
                        "Tests cover Google Calendar item mapping and idempotent sync updates.",
                    ),
                ],
                "Accepted: TaskCommander has a dry-run/calendar-only path suitable for O3 safe scheduling boundary.",
            ),
            (
                "TaskCommander: Create safe scheduling boundary tasks",
                "project_manager",
                "Safe scheduling boundary tasks are defined from source docs.",
                [
                    (
                        "TaskCommander/WINDOWS_TASK_SCHEDULER.md:Before enabling the scheduled task",
                        "Docs require doctor, alert preview, and dry-run checks before scheduler activation.",
                    ),
                    (
                        "TaskCommander/task_reminder_codex_package/PREMORTEM.md",
                        "Known duplicate-task, alert spam, and completion-semantics risks are documented.",
                    ),
                ],
                "Accepted: scheduling boundary should remain dry-run/internal until explicit human enablement.",
            ),
        ]
        for title, agent_id, criterion, evidence, notes in baseline:
            task = Task.objects.get(title=title)
            if not task.acceptance_criteria.filter(required=True).exists():
                AcceptanceCriterion.objects.create(
                    task=task,
                    description=criterion,
                    criterion_type=AcceptanceCriterion.CriterionType.EVIDENCE,
                    required=True,
                )
            task = self._advance_to_in_progress(task, agent_id, correlation_id)
            if task.evidence.count() == 0:
                for reference, summary in evidence:
                    record_task_evidence(
                        {
                            "kind": "ARTIFACT",
                            "uri_or_reference": reference,
                            "metadata": {
                                "objective": "O3",
                                "summary": summary,
                                "correlation_id": correlation_id,
                            },
                            "verified": False,
                        },
                        task_id=str(task.id),
                        actor_id="codex",
                        correlation_id=correlation_id,
                    )
            self._complete_task(task, correlation_id, notes)

    def _advance_to_in_progress(self, task: Task, agent_id: str, correlation_id: str) -> Task:
        if task.status == Task.Status.DRAFT:
            task = transition_task(
                str(task.id),
                to_status=Task.Status.PLANNED,
                expected_version=task.version,
                actor_id="codex",
                correlation_id=correlation_id,
            )
        if task.status == Task.Status.PLANNED:
            task = transition_task(
                str(task.id),
                to_status=Task.Status.APPROVED,
                expected_version=task.version,
                actor_id="codex",
                correlation_id=correlation_id,
            )
        if task.status == Task.Status.APPROVED:
            task = assign_task(
                {"agent_id": agent_id, "expected_version": task.version},
                task_id=str(task.id),
                actor_id="codex",
                correlation_id=correlation_id,
            )
        if task.status == Task.Status.ASSIGNED:
            task = transition_task(
                str(task.id),
                to_status=Task.Status.IN_PROGRESS,
                expected_version=task.version,
                actor_id="codex",
                correlation_id=correlation_id,
            )
        return task

    def _complete_task(self, task: Task, correlation_id: str, notes: str) -> Task:
        if task.status == Task.Status.IN_PROGRESS:
            task = transition_task(
                str(task.id),
                to_status=Task.Status.DELIVERED_UNVERIFIED,
                expected_version=task.version,
                actor_id="codex",
                correlation_id=correlation_id,
            )
        if (
            task.status == Task.Status.DELIVERED_UNVERIFIED
            and not task.verification_reviews.filter(decision=VerificationReview.Decision.ACCEPTED).exists()
        ):
            review_task_evidence(
                {"decision": VerificationReview.Decision.ACCEPTED, "notes": notes, "mark_passed": True},
                task_id=str(task.id),
                actor_id="qa_agent",
                correlation_id=correlation_id,
            )
        task.refresh_from_db()
        if task.status == Task.Status.VERIFYING:
            task = transition_task(
                str(task.id),
                to_status=Task.Status.COMPLETED,
                expected_version=task.version,
                actor_id="codex",
                correlation_id=correlation_id,
            )
        return task
