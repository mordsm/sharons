from django.core.management.base import BaseCommand

from developer.services import create_developer_work_contract, create_implementation_plan, deliver_implementation_plan
from operations.models import Task
from operations.services import assign_task, transition_task
from portfolio.models import Project


class Command(BaseCommand):
    help = "Start O4 REQ-5 through Developer as Sharons governance integration boundary evidence."

    def add_arguments(self, parser):
        parser.add_argument("--actor-id", default="chief_of_staff")
        parser.add_argument("--correlation-id", default="start-o4-req5-developer")

    def handle(self, *args, **options):
        actor_id = options["actor_id"]
        correlation_id = options["correlation_id"]
        project = Project.objects.get(slug="rules-engine")
        connection = project.connections.filter(active=True).first()
        task = Task.objects.get(title="Implement Sharons deterministic rules process spec: REQ-5")

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
                "title": "Define Sharons governance integration boundary",
                "objective": "Define how deterministic rules_engine dry-run evaluations integrate with Sharons governance, approval requests, and audit trace.",
                "scope": [
                    "Define boundary between rules evaluation, approval request creation, and audit logging",
                    "Define allowed internal effects and prohibited external effects",
                    "Define traceability fields for correlation, matched rules, decisions, and human approval",
                ],
                "constraints": {"repo_write": False, "external_action": False, "dry_run_first": True},
                "acceptance_focus": [
                    "Integration boundary preserves human approval for high-risk actions",
                    "Audit trace can show which rule produced which decision",
                    "Rules engine cannot directly execute payment, email, deletion, or external contact",
                ],
            },
            actor_id="developer",
            correlation_id=f"{correlation_id}-contract",
        )
        plan = create_implementation_plan(
            {
                "title": "Sharons governance boundary implementation plan",
                "summary": "Produce evidence for the interface between deterministic rule evaluation and Sharons governance workflows.",
                "planned_changes": [
                    "No repository writes in this step.",
                    "Record boundary contract for dry-run evaluation, approval creation, and audit trace.",
                    "Leave task in DELIVERED_UNVERIFIED for QA acceptance.",
                ],
                "verification_plan": [
                    "Evidence includes input contract, output contract, allowed effects, prohibited effects, and audit metadata.",
                    "Evidence explains when Sharons creates approval requests versus task/file proposals.",
                ],
                "risks": [
                    "A vague boundary could let future agents treat rule output as authorization.",
                    "Missing trace fields would make decisions difficult to audit.",
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
                            "Boundary input: Sharons sends rules_engine only a normalized event payload, dry_run=True, "
                            "actor_id, source_system, correlation_id, policy_version, and redaction_metadata."
                        )
                    },
                    {
                        "uri_or_reference": (
                            "Boundary output: rules_engine returns decision, matched_rules, reason_codes, validation_errors, "
                            "effects, confidence_label, requires_human_approval, and audit_summary. It does not mutate Sharons state."
                        )
                    },
                    {
                        "uri_or_reference": (
                            "Allowed Sharons effects: create internal approval request, create draft task proposal, create draft "
                            "file-link proposal, create escalation brief, record audit event, and mark item for human review."
                        )
                    },
                    {
                        "uri_or_reference": (
                            "Prohibited effects: pay invoice, send email, delete/archive external email, contact person, publish, "
                            "change production configuration, create legal commitment, or spend money."
                        )
                    },
                    {
                        "uri_or_reference": (
                            "Governance trace: every derived approval/task/file/escalation stores correlation_id, source_event_ref, "
                            "policy_version, matched_rules, reason_codes, dry_run flag, reviewer decision, reviewer_id, and reviewed_at."
                        )
                    },
                    {
                        "uri_or_reference": (
                            "Human approval rule: REQUEST_APPROVAL, ESCALATE_TO_OWNER, BLOCK, UNKNOWN, sensitive, legal, financial, "
                            "or external-commitment outputs require human review before any downstream external action is possible."
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
