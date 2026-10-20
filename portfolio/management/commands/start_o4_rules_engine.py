from django.core.management.base import BaseCommand

from operations.models import Task
from operations.services import transition_task
from portfolio.models import Project
from product.models import ProductSpecDraft
from product.services import (
    create_product_spec_contract,
    create_product_spec_draft,
    propose_tasks_from_product_spec_draft,
    review_product_spec_draft,
)


class Command(BaseCommand):
    help = "Start O4 from the existing rules_engine project by creating rule-process spec and tasks."

    def add_arguments(self, parser):
        parser.add_argument("--actor-id", default="chief_of_staff")
        parser.add_argument("--correlation-id", default="start-o4-rules-engine")

    def handle(self, *args, **options):
        actor_id = options["actor_id"]
        correlation_id = options["correlation_id"]
        project = Project.objects.get(slug="rules-engine")
        connection = project.connections.filter(active=True).first()
        task = Task.objects.get(title="Rules Engine: Create rules process-1 and process-2 milestone tasks")

        if task.status == Task.Status.DRAFT:
            task = transition_task(
                str(task.id),
                to_status=Task.Status.PLANNED,
                expected_version=task.version,
                actor_id=actor_id,
                correlation_id=f"{correlation_id}-plan",
            )
            task = transition_task(
                str(task.id),
                to_status=Task.Status.APPROVED,
                expected_version=task.version,
                actor_id=actor_id,
                correlation_id=f"{correlation_id}-approve",
            )

        contract = create_product_spec_contract(
            {
                "task_id": str(task.id),
                "project_id": str(project.id),
                "project_connection_id": connection.id,
                "title": "Sharons deterministic rules process spec",
                "spec_type": "PRD",
                "objective": "Adapt the existing deterministic rules engine into Sharons approval workflows for the first two core operating processes.",
                "target_users": ["Chief of Staff", "Executive Assistant", "Finance Agent", "Project operators"],
                "problem_statement": "Sharons has governance and approval APIs, and rules_engine has structured deterministic evaluation, but the first two real business processes are not yet expressed as validated Sharons rule events and actions.",
                "success_metrics": [
                    "Invoice/receipt/expense classification can be evaluated in dry-run mode with deterministic approval/block/route output.",
                    "Inbound email to task/file/escalate can be evaluated in dry-run mode with deterministic approval/block/route output.",
                    "Each process has schema, fixtures, tests, and a Sharons integration boundary documented.",
                ],
                "requirements": [
                    {"id": "REQ-1", "text": "Assess existing compass_rules event schema, DSL, precedence, and tests for Sharons reuse."},
                    {"id": "REQ-2", "text": "Define structured event schema for invoice/receipt/expense classification."},
                    {"id": "REQ-3", "text": "Define structured event schema for inbound email to task/file/escalate."},
                    {"id": "REQ-4", "text": "Create deterministic rules and fixtures for both first processes."},
                    {"id": "REQ-5", "text": "Define Sharons governance integration boundary: dry-run evaluation, approval request creation, and audit trace."},
                ],
                "constraints": {
                    "llm_authorization_boundary": False,
                    "external_action": False,
                    "first_processes": ["invoice_receipt_expense", "inbound_email_routing"],
                    "existing_project": "rules_engine",
                },
                "open_questions": [
                    "Should rules live in rules_engine, Sharons governance, or both with adapter sync?",
                    "Which fields are mandatory for invoice events from mail_manager?",
                    "Which inbound email classifications should create tasks versus only brief items?",
                ],
                "deliverables": ["rules process spec", "fixtures", "test plan", "integration contract"],
            },
            actor_id="product_manager",
            correlation_id=f"{correlation_id}-contract",
        )
        draft = create_product_spec_draft(
            {
                "title": "Sharons first two deterministic rule processes draft",
                "assumptions": [
                    "compass_rules.py is the strongest existing structured evaluator.",
                    "All first integrations run in dry-run/proposal mode before any external action.",
                ],
                "risks": [
                    "Duplicating rule definitions between Sharons and rules_engine could create drift.",
                    "Financial/email events may contain personal data and require redaction rules.",
                ],
            },
            contract_id=str(contract.id),
            actor_id="product_manager",
            correlation_id=f"{correlation_id}-draft",
        )
        draft = review_product_spec_draft(
            {
                "decision": ProductSpecDraft.ReviewStatus.APPROVED,
                "reviewer_notes": "Ready to decompose into internal implementation tasks.",
            },
            draft_id=str(draft.id),
            actor_id=actor_id,
            correlation_id=f"{correlation_id}-review",
        )
        tasks = propose_tasks_from_product_spec_draft(
            {"limit": 5},
            draft_id=str(draft.id),
            actor_id="product_manager",
            correlation_id=f"{correlation_id}-tasks",
        )
        self.stdout.write(self.style.SUCCESS(f"contract={contract.id}"))
        self.stdout.write(self.style.SUCCESS(f"draft={draft.id}"))
        for proposed_task in tasks:
            self.stdout.write(f"{proposed_task.status}: {proposed_task.title}")
