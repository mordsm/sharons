from django.core.management.base import BaseCommand

from developer.services import create_developer_work_contract, create_implementation_plan, deliver_implementation_plan
from operations.models import Task
from operations.services import assign_task, transition_task
from portfolio.models import Project


class Command(BaseCommand):
    help = "Start O4 REQ-3 through Developer as an evidence-producing inbound email schema task."

    def add_arguments(self, parser):
        parser.add_argument("--actor-id", default="chief_of_staff")
        parser.add_argument("--correlation-id", default="start-o4-req3-developer")

    def handle(self, *args, **options):
        actor_id = options["actor_id"]
        correlation_id = options["correlation_id"]
        project = Project.objects.get(slug="rules-engine")
        connection = project.connections.filter(active=True).first()
        task = Task.objects.get(title="Implement Sharons deterministic rules process spec: REQ-3")

        if task.status == Task.Status.DRAFT:
            task = transition_task(
                str(task.id),
                to_status=Task.Status.PLANNED,
                expected_version=task.version,
                actor_id=actor_id,
                correlation_id=f"{correlation_id}-planned",
            )
            task = transition_task(
                str(task.id),
                to_status=Task.Status.APPROVED,
                expected_version=task.version,
                actor_id=actor_id,
                correlation_id=f"{correlation_id}-approved",
            )
        if task.status == Task.Status.APPROVED:
            task = assign_task(
                {"agent_id": "developer", "expected_version": task.version},
                task_id=str(task.id),
                actor_id=actor_id,
                correlation_id=f"{correlation_id}-assigned",
            )
        if task.status == Task.Status.ASSIGNED:
            task = transition_task(
                str(task.id),
                to_status=Task.Status.IN_PROGRESS,
                expected_version=task.version,
                actor_id="developer",
                correlation_id=f"{correlation_id}-in-progress",
            )

        contract = create_developer_work_contract(
            {
                "task_id": str(task.id),
                "project_id": str(project.id),
                "project_connection_id": connection.id,
                "title": "Define inbound email routing event schema",
                "objective": "Define the first Sharons email rule event for deterministic classification into task creation, file-only handling, escalation, or ignore/review outcomes.",
                "scope": [
                    "Define inbound email event type, message metadata, extracted intent, entity hints, and privacy fields",
                    "Separate task, file, escalation, reminder, newsletter, spam, and unknown routing classes",
                    "Name deterministic effects, human-review cases, blocked cases, and audit requirements",
                ],
                "constraints": {"repo_write": False, "external_action": False, "dry_run_first": True},
                "acceptance_focus": [
                    "Schema supports Executive Assistant triage without sending email",
                    "Low-confidence or sensitive messages route to human review",
                    "Evidence maps outputs to Sharons task/file/escalation workflows",
                ],
            },
            actor_id="developer",
            correlation_id=f"{correlation_id}-contract",
        )
        plan = create_implementation_plan(
            {
                "title": "Inbound email routing schema implementation plan",
                "summary": "Produce an internal schema contract for deterministic inbound email routing before writing code.",
                "planned_changes": [
                    "No repository writes in this step.",
                    "Record inbound email schema and routing evidence in Sharons.",
                    "Leave task in DELIVERED_UNVERIFIED for QA acceptance.",
                ],
                "verification_plan": [
                    "Evidence includes event name, required message fields, classification outputs, effects, and blocked cases.",
                    "Evidence includes examples for create-task, file-only, escalate, and review-needed paths.",
                ],
                "risks": [
                    "Email bodies may contain private data and must be redacted in logs.",
                    "Ambiguous external commitments must not be converted into actions without approval.",
                ],
            },
            contract_id=str(contract.id),
            actor_id="developer",
            correlation_id=f"{correlation_id}-plan",
        )
        plan = deliver_implementation_plan(
            {
                "evidence": [
                    {
                        "uri_or_reference": (
                            "Schema: event_type='inbound_email.route', source_mailbox, message_id, received_at, "
                            "from_address, to_addresses, cc_addresses, subject, body_excerpt_redacted, attachments, "
                            "thread_id, detected_language, sender_relationship, sensitivity_hint, extracted_deadline."
                        )
                    },
                    {
                        "uri_or_reference": (
                            "Validation: require source_mailbox, message_id, received_at, from_address, and subject "
                            "or body_excerpt_redacted. Missing identity or content fields produce BLOCK with "
                            "reason='insufficient_email_routing_data'."
                        )
                    },
                    {
                        "uri_or_reference": (
                            "Routing classes: CREATE_TASK, FILE_ONLY, ESCALATE, REMINDER, NEWSLETTER, SPAM, IGNORE, "
                            "UNKNOWN. UNKNOWN, sensitive, legal, financial, or commitment-bearing messages route "
                            "to human review."
                        )
                    },
                    {
                        "uri_or_reference": (
                            "Deterministic effects: PROPOSE_TASK, PROPOSE_FILE_LINK, REQUEST_APPROVAL, ESCALATE_TO_OWNER, "
                            "BLOCK, AUDIT. No email sending, deletion, archive, or external reply is authorized."
                        )
                    },
                    {
                        "uri_or_reference": (
                            "Sharons mapping: Executive Assistant can use the dry-run decision to draft task proposals, "
                            "filing proposals, or escalation briefs; governance stores reason codes, matched rules, "
                            "redaction metadata, and correlation_id for traceability."
                        )
                    },
                ]
            },
            plan_id=str(plan.id),
            actor_id="developer",
            correlation_id=f"{correlation_id}-deliver",
        )
        self.stdout.write(self.style.SUCCESS(f"task={task.id}"))
        self.stdout.write(self.style.SUCCESS(f"contract={contract.id}"))
        self.stdout.write(self.style.SUCCESS(f"plan={plan.id}"))
        self.stdout.write(self.style.SUCCESS(f"status={plan.status}"))
