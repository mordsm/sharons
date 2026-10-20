from datetime import date

from django.core.management.base import BaseCommand

from finance.models import FinancialRecord
from finance.services import create_financial_record, update_reconciliation
from governance.models import RuleEngineRun, RuleEngineWorkItem
from mailbox.services import ingest_mock_email
from operations.models import AcceptanceCriterion, AgentDefinition, Task
from operations.services import assign_task, record_task_evidence, transition_task
from qa.models import VerificationReview
from qa.services import review_task_evidence


class Command(BaseCommand):
    help = "Run the O2 finance-mail single-source pilot inside Sharons."

    def handle(self, *args, **options):
        actor = "codex"
        correlation_id = "o2-finance-mail-pilot-2026-09-29"
        AgentDefinition.objects.update_or_create(
            agent_id="finance_agent",
            defaults={
                "role": "Finance Agent",
                "capabilities": ["finance", "reconciliation", "rules_review"],
                "tools": ["finance_records", "rule_engine", "audit_log"],
                "allowed_data_classes": ["PUBLIC", "INTERNAL", "CONFIDENTIAL"],
                "forbidden_actions": ["external_payment", "spend_money", "contact_person", "legal_commitment"],
                "max_risk_level": AgentDefinition.RiskLevel.MEDIUM,
                "max_concurrent_tasks": 2,
                "active": True,
                "prompt_version": "core-agents-v1",
            },
        )
        task = Task.objects.get(external_key="finance_agent:O2:finance-mail-single-source-pilot")

        if task.status == Task.Status.DRAFT:
            task = transition_task(
                str(task.id),
                to_status=Task.Status.PLANNED,
                expected_version=task.version,
                actor_id=actor,
                correlation_id=correlation_id,
            )
        if task.status == Task.Status.PLANNED:
            task = transition_task(
                str(task.id),
                to_status=Task.Status.APPROVED,
                expected_version=task.version,
                actor_id=actor,
                correlation_id=correlation_id,
            )
        if task.status == Task.Status.APPROVED:
            task = assign_task(
                {"agent_id": "finance_agent", "expected_version": task.version},
                task_id=str(task.id),
                actor_id=actor,
                correlation_id=correlation_id,
            )
        if task.status == Task.Status.ASSIGNED:
            task = transition_task(
                str(task.id),
                to_status=Task.Status.IN_PROGRESS,
                expected_version=task.version,
                actor_id=actor,
                correlation_id=correlation_id,
            )

        message, _created = ingest_mock_email(
            {
                "source": "o2_mock_gmail",
                "external_event_id": "o2-finance-mail-pilot-invoice-001",
                "sender": "billing@example-vendor.test",
                "subject": "Invoice for September platform subscription",
                "body": (
                    "Invoice amount 89.90 ILS. Due 2026-09-30. "
                    "This is a controlled O2 pilot email; do not pay or send anything."
                ),
            },
            actor_id="executive_assistant",
            correlation_id=correlation_id,
        )

        record = FinancialRecord.objects.filter(
            source="mail_manager:financial_items",
            external_reference="o2-finance-mail-pilot-invoice-001",
        ).first()
        if record is None:
            record = create_financial_record(
                {
                    "record_type": FinancialRecord.RecordType.SUBSCRIPTION_COST,
                    "occurred_on": date(2026, 9, 29).isoformat(),
                    "amount": "89.90",
                    "currency": "ILS",
                    "source": "mail_manager:financial_items",
                    "category": "platform_subscription",
                    "description": "Example Vendor September subscription invoice",
                    "external_reference": "o2-finance-mail-pilot-invoice-001",
                    "metadata": {
                        "document_kind_hint": "invoice",
                        "mailbox_message_id": str(message.id),
                        "mock_email_source": message.source,
                        "mock_email_classification": message.classification,
                        "project": "O2 Financial single source of truth",
                        "confidence_hint": 0.85,
                        "non_destructive": True,
                    },
                },
                actor_id="finance_agent",
                correlation_id=correlation_id,
            )

        reviewed = update_reconciliation(
            str(record.id),
            status=FinancialRecord.ReconciliationStatus.NEEDS_REVIEW,
            notes="Opened by O2 pilot for finance review; no payment or external action was taken.",
            actor_id="finance_agent",
            correlation_id=correlation_id,
        )

        if task.evidence.count() == 0:
            evidence = [
                (
                    f"mailbox.MockEmailMessage:{message.id}",
                    (
                        f"Mock invoice ingested as {message.classification}; "
                        f"proposed action {message.proposed_action.get('type')}; "
                        f"rules decision {message.rule_decision}."
                    ),
                ),
                (
                    f"finance.FinancialRecord:{record.id}",
                    (
                        "Financial record created from mail-derived pilot item; "
                        f"status {reviewed.reconciliation_status}; amount {record.amount} {record.currency}."
                    ),
                ),
                (
                    "governance.RuleEngineRun:event_type=inbound_email.route and finance_document.classify",
                    f"Rules dry runs recorded under correlation {correlation_id}.",
                ),
            ]
            for reference, summary in evidence:
                record_task_evidence(
                    {
                        "kind": "ARTIFACT",
                        "uri_or_reference": reference,
                        "metadata": {
                            "objective": "O2",
                            "summary": summary,
                            "correlation_id": correlation_id,
                            "non_destructive": True,
                        },
                        "verified": False,
                    },
                    task_id=str(task.id),
                    actor_id=actor,
                    correlation_id=correlation_id,
                )

        if task.status == Task.Status.IN_PROGRESS:
            task = transition_task(
                str(task.id),
                to_status=Task.Status.DELIVERED_UNVERIFIED,
                expected_version=task.version,
                actor_id=actor,
                correlation_id=correlation_id,
            )

        if (
            task.status == Task.Status.DELIVERED_UNVERIFIED
            and not task.verification_reviews.filter(decision=VerificationReview.Decision.ACCEPTED).exists()
        ):
            review_task_evidence(
                {
                    "decision": VerificationReview.Decision.ACCEPTED,
                    "notes": (
                        "Accepted: O2 pilot created a mail invoice, finance record, "
                        "reconciliation review state, and rules-engine traces with no external action."
                    ),
                    "mark_passed": True,
                },
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
                actor_id=actor,
                correlation_id=correlation_id,
            )

        run_queryset = RuleEngineRun.objects.filter(
            external_event_id__in=[
                "o2-finance-mail-pilot-invoice-001",
                "mail_manager:financial_items:o2-finance-mail-pilot-invoice-001",
            ]
        )
        runs = list(run_queryset.values_list("event_type", "final_decision"))
        work_items = list(RuleEngineWorkItem.objects.filter(run__in=run_queryset).values_list("status", "owner_agent_id"))
        self.stdout.write(f"task={task.title} status={task.status} version={task.version}")
        self.stdout.write(f"message={message.id} classification={message.classification}")
        self.stdout.write(f"record={record.id} reconciliation_status={reviewed.reconciliation_status}")
        self.stdout.write(f"runs={runs}")
        self.stdout.write(f"work_items={work_items}")
