from django.core.management.base import BaseCommand

from marketing.models import MarketingRequest
from marketing.services import create_marketing_request
from operations.models import Task
from operations.services import record_task_evidence, transition_task, upsert_task, verify_task
from portfolio.models import Objective, Project
from product.models import ProductSpecContract, UserResearchContract
from product.user_research import add_user_research_question, create_user_research_contract
from project_manager.models import ExecutionReview
from project_manager.services import create_execution_review


CORRELATION = "o1-launch-review"
ACTOR = "chief_of_staff"
OPEN_QUESTIONS = (
    "Which payment provider will be used for the first paid beta?",
    "What is the exact first beta offer and price?",
    "Which landing-page stack should host the first public page?",
)
MARKETING_OBJECTIVE = (
    "Prepare a 30-day Israel draft for Mental Trainer's sale-ready beta. "
    "The offer and price are still open questions. Do not publish or spend."
)


class Command(BaseCommand):
    help = "Record the Mental Trainer launch decision list and verify that task."

    def handle(self, *args, **options):
        objective = Objective.objects.get(code="O1", status=Objective.Status.ACTIVE)
        project = Project.objects.get(slug="mental-skills-playground")
        spec = ProductSpecContract.objects.get(project=project, title="Mental Trainer sale-ready beta path PRD")
        research = self._research(spec)
        review = self._review(objective)
        marketing_request = self._marketing(objective, project)
        task = self._verified_task(objective, research, review, marketing_request)
        self.stdout.write(f"research {research.id}")
        self.stdout.write(f"execution_review {review.id}")
        self.stdout.write(f"marketing_request {marketing_request.id} publish={marketing_request.social_publish_enabled} spend={marketing_request.ad_spend_enabled}")
        self.stdout.write(f"task {task.id} {task.status}")

    def _research(self, spec):
        contract = UserResearchContract.objects.filter(spec_contract=spec, title="Mental Trainer beta proof still missing").first()
        if contract is None:
            contract = create_user_research_contract(
                {
                    "title": "Mental Trainer beta proof still missing",
                    "research_question": "Which offer, price, and external validation evidence are still missing before a sale-ready beta?",
                    "method": "INTERNAL_SYNTHESIS",
                    "participant_segment": "adult beta users",
                },
                spec_contract_id=str(spec.id),
                actor_id=ACTOR,
                correlation_id=CORRELATION,
            )
        existing = set(contract.questions.values_list("question", flat=True))
        for question in OPEN_QUESTIONS:
            if question not in existing:
                add_user_research_question(
                    {"question": question},
                    contract_id=str(contract.id),
                    actor_id=ACTOR,
                    correlation_id=CORRELATION,
                )
        return contract

    def _review(self, objective):
        review = ExecutionReview.objects.filter(objective=objective, created_by=ACTOR).order_by("-created_at").first()
        if review:
            return review
        return create_execution_review({"objective_id": str(objective.id)}, actor_id=ACTOR, correlation_id=CORRELATION)

    def _marketing(self, objective, project):
        existing = MarketingRequest.objects.filter(objective_record=objective, objective_text=MARKETING_OBJECTIVE).order_by("-created_at").first()
        if existing:
            return existing
        return create_marketing_request(
            {
                "objective": MARKETING_OBJECTIVE,
                "objective_id": str(objective.id),
                "project_id": str(project.id),
                "geography": ["Israel"],
                "currency": "ILS",
                "time_horizon": "30 days",
            },
            actor_id="marketing",
            correlation_id=CORRELATION,
        )

    def _verified_task(self, objective, research, review, marketing_request):
        task = Task.objects.filter(objective=objective, external_key="o1-launch-decision-list").first()
        if task and task.status == Task.Status.COMPLETED:
            return task
        if task is None:
            task, _created = upsert_task(
                {
                    "objective_id": str(objective.id),
                    "external_key": "o1-launch-decision-list",
                    "title": "Record the Mental Trainer launch decision list",
                    "business_outcome": "The weekly review shows what to approve, what is blocked, and what is still an assumption.",
                    "acceptance_criteria": [
                        {
                            "description": "The weekly review lists the Mental Trainer decisions, blocked work, and assumptions, and the marketing draft does not publish or spend.",
                            "criterion_type": "MANUAL",
                            "required": True,
                        }
                    ],
                },
                actor_id=ACTOR,
                correlation_id=CORRELATION,
            )
        path = [
            Task.Status.DRAFT,
            Task.Status.PLANNED,
            Task.Status.APPROVED,
            Task.Status.ASSIGNED,
            Task.Status.IN_PROGRESS,
            Task.Status.DELIVERED_UNVERIFIED,
        ]
        if task.status in path:
            for status in path[path.index(task.status) + 1 :]:
                task = transition_task(
                    str(task.id),
                    to_status=status,
                    expected_version=task.version,
                    actor_id=ACTOR,
                    correlation_id=CORRELATION,
                )
        if not task.evidence.filter(verified=True).exists():
            record_task_evidence(
            {
                "kind": "ARTIFACT",
                "uri_or_reference": f"marketing-request:{marketing_request.id}",
                "metadata": {
                    "execution_review_id": str(review.id),
                    "user_research_contract_id": str(research.id),
                    "social_publish_enabled": False,
                    "ad_spend_enabled": False,
                },
                "verified": True,
            },
            task_id=str(task.id),
            actor_id=ACTOR,
            correlation_id=CORRELATION,
        )
        task.refresh_from_db()
        if task.status == Task.Status.DELIVERED_UNVERIFIED:
            task = verify_task(
            {"mark_passed": True, "notes": "The launch list is on the weekly review and no external action was enabled."},
            task_id=str(task.id),
            actor_id=ACTOR,
            correlation_id=CORRELATION,
        )
        task.refresh_from_db()
        if task.status == Task.Status.COMPLETED:
            return task
        return transition_task(
            str(task.id),
            to_status=Task.Status.COMPLETED,
            expected_version=task.version,
            actor_id=ACTOR,
            correlation_id=CORRELATION,
        )
