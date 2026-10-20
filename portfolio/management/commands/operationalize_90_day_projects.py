from django.core.management.base import BaseCommand

from portfolio.models import Objective, ProjectStateAssessment
from portfolio.services import register_known_90_day_projects
from project_manager.services import create_execution_review, propose_milestones


class Command(BaseCommand):
    help = "Register known 90-day projects and create gap-based execution reviews and milestone proposals."

    def add_arguments(self, parser):
        parser.add_argument("--actor-id", default="chief_of_staff")
        parser.add_argument("--correlation-id", default="operationalize-90-day-projects")

    def handle(self, *args, **options):
        actor_id = options["actor_id"]
        correlation_id = options["correlation_id"]
        register_known_90_day_projects(actor_id=actor_id, correlation_id=f"{correlation_id}-register")

        for objective in Objective.objects.filter(status=Objective.Status.ACTIVE).order_by("code"):
            create_execution_review(
                {"objective_id": str(objective.id)},
                actor_id=actor_id,
                correlation_id=f"{correlation_id}-{objective.code}-review",
            )
            milestones = []
            assessments = ProjectStateAssessment.objects.filter(
                objective=objective,
                status=ProjectStateAssessment.Status.CURRENT,
            ).select_related("project")
            for assessment in assessments:
                for index, step in enumerate(assessment.recommended_next_steps[:2], start=1):
                    milestones.append(
                        {
                            "key": f"{assessment.project.slug}-step-{index}",
                            "title": f"{assessment.project.name}: {step}",
                            "rationale": f"Gap-based next step from current-state assessment for {assessment.project.name}.",
                        }
                    )
            if milestones:
                propose_milestones(
                    {"milestones": milestones},
                    objective_id=str(objective.id),
                    actor_id=actor_id,
                    correlation_id=f"{correlation_id}-{objective.code}-milestones",
                )
            self.stdout.write(self.style.SUCCESS(f"{objective.code}: execution review and {len(milestones)} milestone proposals"))
