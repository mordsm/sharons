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
    help = "Start O1 from the existing Mental Skills Playground project by creating PM spec and gap tasks."

    def add_arguments(self, parser):
        parser.add_argument("--actor-id", default="chief_of_staff")
        parser.add_argument("--correlation-id", default="start-o1-mental-trainer")

    def handle(self, *args, **options):
        actor_id = options["actor_id"]
        correlation_id = options["correlation_id"]
        project = Project.objects.get(slug="mental-skills-playground")
        connection = project.connections.filter(active=True).first()
        task = Task.objects.get(title="Mental Skills Playground / Mental Trainer: Create PM spec for sale-ready beta path")

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
                "title": "Mental Trainer sale-ready beta path PRD",
                "spec_type": "PRD",
                "objective": "Define the sale-ready beta journey for Mental Skills Playground / Mental Trainer using the existing backend and GPT Actions API.",
                "target_users": [
                    "adult beta user seeking short mental-skill practice",
                    "owner/operator validating willingness to pay",
                ],
                "problem_statement": "The product has a working mental-skills training backend, but is not yet packaged as a sale-ready desktop/mobile beta with pricing, landing page, billing path, and external validation evidence.",
                "success_metrics": [
                    "5 external beta users can complete DISCOVER -> TRAIN -> RETEST -> TRANSFER -> LEARN without hand-holding",
                    "pricing and billing path are documented and testable",
                    "landing page communicates non-therapy training positioning and conversion CTA",
                    "desktop and mobile journeys pass smoke testing",
                ],
                "requirements": [
                    {"id": "REQ-1", "text": "Document the current backend/GPT Actions journey and identify missing sale-ready screens or flows."},
                    {"id": "REQ-2", "text": "Define landing page content, CTA, and non-therapy safety positioning."},
                    {"id": "REQ-3", "text": "Define pricing and billing test path for initial beta."},
                    {"id": "REQ-4", "text": "Define desktop and mobile smoke-test acceptance criteria."},
                    {"id": "REQ-5", "text": "Define external beta validation protocol and evidence to collect."},
                ],
                "constraints": {
                    "external_write": False,
                    "medical_safety": "not therapy, diagnosis, or medical advice",
                    "existing_project": "mental-skills-playground",
                },
                "open_questions": [
                    "Which payment provider will be used for the first paid beta?",
                    "What is the exact first beta offer and price?",
                    "Which landing-page stack should host the first public page?",
                ],
                "deliverables": ["PRD", "implementation task proposals", "beta validation checklist"],
            },
            actor_id="product_manager",
            correlation_id=f"{correlation_id}-contract",
        )
        draft = create_product_spec_draft(
            {
                "title": "Mental Trainer sale-ready beta path draft",
                "assumptions": [
                    "Existing FastAPI backend remains the training service of record.",
                    "Sharons coordinates work but does not own product code.",
                ],
                "risks": [
                    "Medical/therapy positioning must remain clear.",
                    "Billing and external beta introduce approval-sensitive actions.",
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
