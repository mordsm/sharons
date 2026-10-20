from django.core.management.base import BaseCommand

from developer.services import create_developer_work_contract, create_implementation_plan, deliver_implementation_plan
from operations.models import Task
from operations.services import assign_task, transition_task
from portfolio.models import Project


class Command(BaseCommand):
    help = "Start O4 REQ-4 through Developer as deterministic rules and fixtures evidence."

    def add_arguments(self, parser):
        parser.add_argument("--actor-id", default="chief_of_staff")
        parser.add_argument("--correlation-id", default="start-o4-req4-developer")

    def handle(self, *args, **options):
        actor_id = options["actor_id"]
        correlation_id = options["correlation_id"]
        project = Project.objects.get(slug="rules-engine")
        connection = project.connections.filter(active=True).first()
        task = Task.objects.get(title="Implement Sharons deterministic rules process spec: REQ-4")

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
                "title": "Create deterministic rule fixtures for first Sharons processes",
                "objective": "Define initial deterministic dry-run rules and fixtures for finance document classification and inbound email routing.",
                "scope": [
                    "Specify finance rules for invoice approval request, receipt filing, missing data blocking, and unknown review",
                    "Specify inbound email rules for task proposal, file-only proposal, escalation, and sensitive review",
                    "Specify fixture inputs and expected effects for both processes",
                ],
                "constraints": {"repo_write": False, "external_action": False, "dry_run_first": True},
                "acceptance_focus": [
                    "Rules are deterministic and ordered by explicit precedence",
                    "Fixtures include positive, negative, and unknown/review cases",
                    "No rule authorizes payment, email sending, deletion, archive, or external contact",
                ],
            },
            actor_id="developer",
            correlation_id=f"{correlation_id}-contract",
        )
        plan = create_implementation_plan(
            {
                "title": "First deterministic rules and fixtures plan",
                "summary": "Produce evidence for the rule set and fixture expectations before code integration.",
                "planned_changes": [
                    "No repository writes in this step.",
                    "Record finance and inbound email rule fixtures in Sharons.",
                    "Leave task in DELIVERED_UNVERIFIED for QA acceptance.",
                ],
                "verification_plan": [
                    "Evidence includes rule names, precedence, matching conditions, effects, and fixture expectations.",
                    "Evidence covers at least two finance fixtures and two inbound email fixtures plus blocked/review paths.",
                ],
                "risks": [
                    "Rules may be too broad and over-route ambiguous events.",
                    "Fixture coverage is conceptual until implemented in rules_engine tests.",
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
                            "Finance rules: F1 missing_required_finance_fields -> BLOCK; F2 payable_invoice_detected "
                            "with amount/vendor/due_date -> REQUEST_APPROVAL and ROUTE finance_owner; F3 paid_receipt "
                            "with paid_at/payment_method -> APPROVE safe filing; F4 unknown_or_low_confidence -> ROUTE human_review."
                        )
                    },
                    {
                        "uri_or_reference": (
                            "Finance fixtures: invoice_acme_1200_usd expects REQUEST_APPROVAL+AUDIT; "
                            "receipt_office_supplies_paid expects APPROVE filing+AUDIT; finance_missing_document_ref "
                            "expects BLOCK; ambiguous_subscription_notice expects ROUTE human_review."
                        )
                    },
                    {
                        "uri_or_reference": (
                            "Email rules: E1 missing_message_identity -> BLOCK; E2 deadline_or_action_request from trusted sender "
                            "-> PROPOSE_TASK; E3 attachment_without_action -> PROPOSE_FILE_LINK; E4 sensitive/legal/financial "
                            "or external commitment -> REQUEST_APPROVAL/ESCALATE_TO_OWNER; E5 newsletter/spam -> AUDIT only."
                        )
                    },
                    {
                        "uri_or_reference": (
                            "Email fixtures: board_followup_due_tuesday expects PROPOSE_TASK+AUDIT; vendor_invoice_attachment "
                            "expects PROPOSE_FILE_LINK plus finance route; legal_contract_question expects ESCALATE_TO_OWNER; "
                            "unknown_sender_commitment_request expects REQUEST_APPROVAL human_review."
                        )
                    },
                    {
                        "uri_or_reference": (
                            "Precedence and safety: BLOCK rules run before routing; sensitive/escalation rules run before "
                            "task/file proposals; dry_run produces effects only; prohibited effects include SEND_EMAIL, "
                            "DELETE_EMAIL, PAY_INVOICE, ARCHIVE_EXTERNAL, or CONTACT_PERSON."
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
