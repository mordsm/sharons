from django.core.management.base import BaseCommand

from developer.services import create_developer_work_contract, create_implementation_plan, deliver_implementation_plan
from operations.models import Task
from operations.services import transition_task
from portfolio.models import Project


class Command(BaseCommand):
    help = "Start O4 REQ-1 through Developer as an evidence-producing assessment task."

    def add_arguments(self, parser):
        parser.add_argument("--actor-id", default="chief_of_staff")
        parser.add_argument("--correlation-id", default="start-o4-req1-developer")

    def handle(self, *args, **options):
        actor_id = options["actor_id"]
        correlation_id = options["correlation_id"]
        project = Project.objects.get(slug="rules-engine")
        connection = project.connections.filter(active=True).first()
        task = Task.objects.get(title="Implement Sharons deterministic rules process spec: REQ-1")

        if task.status == Task.Status.DRAFT:
            task = transition_task(str(task.id), to_status=Task.Status.PLANNED, expected_version=task.version, actor_id=actor_id, correlation_id=f"{correlation_id}-planned")
            task = transition_task(str(task.id), to_status=Task.Status.APPROVED, expected_version=task.version, actor_id=actor_id, correlation_id=f"{correlation_id}-approved")
        if task.status == Task.Status.APPROVED:
            task.owner_agent_id = "developer"
            task.status = Task.Status.ASSIGNED
            task.version += 1
            task.save(update_fields=["owner_agent_id", "status", "version", "updated_at"])
        if task.status == Task.Status.ASSIGNED:
            task = transition_task(str(task.id), to_status=Task.Status.IN_PROGRESS, expected_version=task.version, actor_id="developer", correlation_id=f"{correlation_id}-in-progress")

        contract = create_developer_work_contract(
            {
                "task_id": str(task.id),
                "project_id": str(project.id),
                "project_connection_id": connection.id,
                "title": "Assess compass_rules for Sharons reuse",
                "objective": "Assess existing rules_engine structured evaluator, schema, precedence, and tests for reuse in Sharons governance.",
                "scope": [
                    "Read compass_rules.py schema and evaluator",
                    "Read tests/test_compass_rules.py",
                    "Identify fit/gaps for invoice and inbound-email processes",
                ],
                "constraints": {"repo_write": False, "external_action": False},
                "acceptance_focus": ["Assessment evidence names concrete files and first reuse gaps."],
            },
            actor_id="developer",
            correlation_id=f"{correlation_id}-contract",
        )
        plan = create_implementation_plan(
            {
                "title": "Rules evaluator assessment plan",
                "summary": "Inspect existing structured rules evaluator and produce evidence for Sharons reuse decisions.",
                "planned_changes": [
                    "No code changes; assessment only.",
                    "Record evidence from rules_engine/compass_rules.py and tests.",
                    "Deliver findings into Sharons verification queue.",
                ],
                "verification_plan": [
                    "Evidence references compass_rules.py, test_compass_rules.py, and pyproject.toml.",
                    "Task ends as DELIVERED_UNVERIFIED for QA/CoS verification.",
                ],
                "risks": ["Assessment may reveal that rules_engine and Sharons governance duplicate responsibilities."],
            },
            contract_id=str(contract.id),
            actor_id="developer",
            correlation_id=f"{correlation_id}-plan",
        )
        plan = deliver_implementation_plan(
            {
                "evidence": [
                    {
                        "uri_or_reference": "rules_engine/compass_rules.py: structured event schema, typed payloads, precedence, and deterministic effects already exist."
                    },
                    {
                        "uri_or_reference": "rules_engine/tests/test_compass_rules.py: evaluator has coverage for approval, routing, risk, block, dry-run, and validation behavior."
                    },
                    {
                        "uri_or_reference": "rules_engine/pyproject.toml: package is small and reusable with pydantic/PyYAML dependencies."
                    },
                    {
                        "uri_or_reference": "Gap: existing structured payloads cover assessment/fitness/admin events, but not invoice/receipt/expense or inbound_email_routing yet."
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
