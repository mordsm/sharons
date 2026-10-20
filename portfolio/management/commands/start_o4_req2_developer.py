from django.core.management.base import BaseCommand

from developer.services import create_developer_work_contract, create_implementation_plan, deliver_implementation_plan
from operations.models import Task
from operations.services import assign_task, transition_task
from portfolio.models import Project


class Command(BaseCommand):
    help = "Start O4 REQ-2 through Developer as an evidence-producing finance event schema task."

    def add_arguments(self, parser):
        parser.add_argument("--actor-id", default="chief_of_staff")
        parser.add_argument("--correlation-id", default="start-o4-req2-developer")

    def handle(self, *args, **options):
        actor_id = options["actor_id"]
        correlation_id = options["correlation_id"]
        project = Project.objects.get(slug="rules-engine")
        connection = project.connections.filter(active=True).first()
        task = Task.objects.get(title="Implement Sharons deterministic rules process spec: REQ-2")

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
                "title": "Define finance classification event schema",
                "objective": "Define the first Sharons finance rule event for invoice, receipt, and expense classification in deterministic dry-run mode.",
                "scope": [
                    "Define event type, payload, context, and actor fields for finance documents",
                    "Separate invoice, receipt, reimbursement, subscription, and unknown classifications",
                    "Name required validation errors, routing effects, approval effects, and audit metadata",
                ],
                "constraints": {"repo_write": False, "external_action": False, "dry_run_first": True},
                "acceptance_focus": [
                    "Schema has required fields and unknown-safe defaults",
                    "Classification outputs include approval, route, block, and review-needed decisions",
                    "Evidence identifies how it maps to compass_rules structured events",
                ],
            },
            actor_id="developer",
            correlation_id=f"{correlation_id}-contract",
        )
        plan = create_implementation_plan(
            {
                "title": "Finance event schema implementation plan",
                "summary": "Produce an internal schema contract for deterministic finance document classification before writing code.",
                "planned_changes": [
                    "No repository writes in this step.",
                    "Record finance event schema and validation evidence in Sharons.",
                    "Leave task in DELIVERED_UNVERIFIED for QA acceptance.",
                ],
                "verification_plan": [
                    "Evidence includes event name, required payload fields, optional context fields, decision types, and audit trace requirements.",
                    "Evidence includes examples for invoice, receipt, expense, and unknown document cases.",
                ],
                "risks": [
                    "Finance inputs may contain private data and must be redacted in logs.",
                    "Ambiguous documents must route to human review instead of being force-classified.",
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
                            "Schema: event_type='finance_document.classify', source_system, received_at, "
                            "document_ref, document_kind_hint, vendor_name, amount, currency, due_date, paid_at, "
                            "payment_method, account_hint, project_or_household_context, requester, confidence_hint."
                        )
                    },
                    {
                        "uri_or_reference": (
                            "Validation: require document_ref, source_system, received_at, and at least one of "
                            "vendor_name/amount/document_kind_hint. Missing required fields produce BLOCK with "
                            "reason='insufficient_finance_document_data'."
                        )
                    },
                    {
                        "uri_or_reference": (
                            "Classification outputs: INVOICE, RECEIPT, EXPENSE, REIMBURSEMENT, SUBSCRIPTION, "
                            "UNKNOWN. UNKNOWN and low-confidence cases route to human review; no payment or external "
                            "communication is authorized."
                        )
                    },
                    {
                        "uri_or_reference": (
                            "Deterministic effects: APPROVE for safe filing, ROUTE to finance/project owner, "
                            "REQUEST_APPROVAL for payable invoice, BLOCK for missing data or policy violation, "
                            "AUDIT only for dry-run."
                        )
                    },
                    {
                        "uri_or_reference": (
                            "compass_rules mapping: use structured event payload plus evaluation context; preserve "
                            "rule precedence, validation errors, dry_run flag, effects list, decision reasons, and "
                            "audit metadata for Sharons governance traceability."
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
