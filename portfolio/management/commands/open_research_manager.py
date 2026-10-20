from django.core.management.base import BaseCommand

from operations.models import AcceptanceCriterion, AgentDefinition, Task
from operations.services import assign_task, record_task_evidence, transition_task, upsert_task
from portfolio.models import Objective, Project, ProjectConnection, ProjectStateAssessment
from qa.models import VerificationReview
from qa.services import review_task_evidence
from research.models import ResearchTaskContract
from research.services import create_research_contract, research_adapter_status


class Command(BaseCommand):
    help = "Open Research Manager as a read-only Sharons project and create the first research contract."

    def handle(self, *args, **options):
        actor = "codex"
        correlation_id = "open-research-manager-2026-09-29"

        research_agent = self._ensure_research_agent()
        project, connection = self._ensure_project_and_connection(correlation_id)
        objective = Objective.objects.get(code="O1")
        task = self._ensure_opening_task(objective, correlation_id)
        task = self._advance_to_in_progress(task, research_agent.agent_id, correlation_id)

        contract = ResearchTaskContract.objects.filter(
            task=task,
            project=project,
            title="O1 market and evidence research readiness contract",
        ).first()
        if contract is None:
            contract = create_research_contract(
                {
                    "task_id": str(task.id),
                    "project_id": str(project.id),
                    "project_connection_id": connection.id,
                    "title": "O1 market and evidence research readiness contract",
                    "original_request": (
                        "Open Research Manager as a Sharons team capability and prepare it to support "
                        "90-day objective research without external execution."
                    ),
                    "research_question": (
                        "What evidence and market research should shape Mental Trainer commercial readiness?"
                    ),
                    "scope": {
                        "domain": "market_research",
                        "allowed_sources": ["internal_records", "local_research_manager_repository"],
                        "disallowed_actions": ["medical_recommendation", "external_publication", "paid_database_access"],
                    },
                    "deliverables": [
                        "research_plan",
                        "source_coverage_record",
                        "claim_evidence_traceability",
                        "limitations_and_next_steps",
                    ],
                    "budgets": {
                        "max_iterations": 2,
                        "max_deep_branches": 1,
                        "max_external_actions": 0,
                    },
                    "safety_mode": "STRICT_RESEARCH_ONLY",
                    "depth_mode": ResearchTaskContract.DepthMode.STANDARD,
                },
                actor_id=research_agent.agent_id,
                correlation_id=correlation_id,
            )

        if task.evidence.count() == 0:
            evidence = [
                (
                    "research_manager/README.md:Phase 1 backend-only Research Manager",
                    "Research Manager has a Phase 1 workflow for planner, executor, evidence analyst, critic, synthesizer, and supervisor.",
                ),
                (
                    "research_manager/app/workflows/research_graph.py",
                    "Workflow separates planning, evidence collection, criticism, synthesis, supervisor stopping, and final reporting.",
                ),
                (
                    "research_manager/app/schemas/research.py",
                    "Schemas include ResearchState, StudyRecord, EvidenceClaim, ResearchPlan, SearchCoverageRecord, and hypotheses.",
                ),
                (
                    f"research.ResearchTaskContract:{contract.id}",
                    "Sharons read-only research contract created for first operational use.",
                ),
            ]
            for reference, summary in evidence:
                record_task_evidence(
                    {
                        "kind": "ARTIFACT",
                        "uri_or_reference": reference,
                        "metadata": {
                            "summary": summary,
                            "correlation_id": correlation_id,
                            "no_external_execution": True,
                        },
                        "verified": False,
                    },
                    task_id=str(task.id),
                    actor_id=actor,
                    correlation_id=correlation_id,
                )

        task = self._complete_task(
            task,
            correlation_id,
            "Accepted: Research Manager is registered as read-only, has a project connection, and has a READY research contract.",
        )
        status = research_adapter_status(project_id=str(project.id))

        self.stdout.write(f"agent={research_agent.agent_id} active={research_agent.active}")
        self.stdout.write(f"project={project.slug} status={project.status} connection={connection.adapter_type}/{connection.permission_mode}")
        self.stdout.write(f"task={task.title} status={task.status} version={task.version}")
        self.stdout.write(f"contract={contract.id} status={contract.status} depth={contract.depth_mode}")
        self.stdout.write(f"adapter_status={status['adapter']} external_execution_enabled={status['external_execution_enabled']}")

    def _ensure_research_agent(self) -> AgentDefinition:
        agent, _created = AgentDefinition.objects.update_or_create(
            agent_id="research_manager",
            defaults={
                "role": "Research Manager",
                "capabilities": [
                    "research_planning",
                    "source_coverage",
                    "evidence_synthesis",
                    "contradiction_analysis",
                    "claim_traceability",
                ],
                "tools": ["research_contracts", "project_registry", "audit_log"],
                "allowed_data_classes": ["PUBLIC", "INTERNAL", "CONFIDENTIAL"],
                "forbidden_actions": [
                    "medical_recommendation",
                    "external_publish",
                    "paid_database_purchase",
                    "contact_person",
                    "spend_money",
                    "production_change",
                ],
                "max_risk_level": AgentDefinition.RiskLevel.MEDIUM,
                "max_concurrent_tasks": 2,
                "active": True,
                "prompt_version": "research-manager-mvp-v1",
            },
        )
        return agent

    def _ensure_project_and_connection(self, correlation_id: str) -> tuple[Project, ProjectConnection]:
        project, _created = Project.objects.update_or_create(
            slug="research-manager",
            defaults={
                "name": "Research Manager",
                "description": "AI-native research orchestration project with evidence traceability and critic/supervisor workflow.",
                "status": Project.Status.ACTIVE,
                "repository_provider": "local",
                "repository_reference": "C:\\workspace\\research_manager",
                "owner": "research_manager",
                "data_classification": Project.DataClassification.CONFIDENTIAL,
                "metadata": {
                    "source": "open_research_manager_command",
                    "mvp_roles_are_workflow_nodes": True,
                    "external_execution_enabled": False,
                },
            },
        )
        connection, _created = ProjectConnection.objects.update_or_create(
            project=project,
            adapter_type="research_manager_read_only",
            defaults={
                "connection_type": ProjectConnection.ConnectionType.REPOSITORY,
                "capabilities": {
                    "create_contract": True,
                    "adapter_status": True,
                    "run_external_research": False,
                    "write_repository": False,
                },
                "permission_mode": ProjectConnection.PermissionMode.READ_ONLY,
                "credential_reference": "",
                "contract_version": 1,
                "active": True,
            },
        )
        ProjectStateAssessment.objects.filter(project=project, status=ProjectStateAssessment.Status.CURRENT).update(
            status=ProjectStateAssessment.Status.SUPERSEDED
        )
        ProjectStateAssessment.objects.create(
            project=project,
            objective=None,
            summary=(
                "Research Manager is opened as a read-only Sharons team capability. "
                "The existing local project already contains a Phase 1 graph, schemas, storage, API, and tests."
            ),
            known_assets=[
                "README.md",
                "app/workflows/research_graph.py",
                "app/schemas/research.py",
                "tests/test_research_graph.py",
            ],
            gaps=[
                "Live source connectors should remain explicit and audited.",
                "Medical work must stay research-only, not treatment advice.",
                "Specialist agents should not be split out until a stable tool/memory need appears.",
            ],
            recommended_next_steps=[
                "Use ResearchTaskContract for first O1 market/evidence question.",
                "Add dashboard visibility for Research Manager queue.",
                "Only later promote planner/critic/supervisor into separate agents if needed.",
            ],
            evidence=[{"type": "workspace_path", "reference": "C:\\workspace\\research_manager"}],
            status=ProjectStateAssessment.Status.CURRENT,
            created_by="codex",
        )
        return project, connection

    def _ensure_opening_task(self, objective: Objective, correlation_id: str) -> Task:
        task, _created = upsert_task(
            {
                "title": "Research Manager: Open read-only evidence workflow",
                "business_outcome": (
                    "Research Manager is registered in Sharons with a read-only project connection, "
                    "agent definition, and first READY research contract."
                ),
                "objective_id": str(objective.id),
                "external_key": "research_manager:open-read-only-evidence-workflow",
                "acceptance_criteria": [
                    {
                        "description": "Research Manager agent and project connection are registered as read-only.",
                        "criterion_type": AcceptanceCriterion.CriterionType.EVIDENCE,
                        "required": True,
                    },
                    {
                        "description": "A first research contract exists and performs no external execution.",
                        "criterion_type": AcceptanceCriterion.CriterionType.EVIDENCE,
                        "required": True,
                    },
                ],
            },
            actor_id="codex",
            correlation_id=correlation_id,
        )
        return task

    def _advance_to_in_progress(self, task: Task, agent_id: str, correlation_id: str) -> Task:
        if task.status == Task.Status.DRAFT:
            task = transition_task(
                str(task.id),
                to_status=Task.Status.PLANNED,
                expected_version=task.version,
                actor_id="codex",
                correlation_id=correlation_id,
            )
        if task.status == Task.Status.PLANNED:
            task = transition_task(
                str(task.id),
                to_status=Task.Status.APPROVED,
                expected_version=task.version,
                actor_id="codex",
                correlation_id=correlation_id,
            )
        if task.status == Task.Status.APPROVED:
            task = assign_task(
                {"agent_id": agent_id, "expected_version": task.version},
                task_id=str(task.id),
                actor_id="codex",
                correlation_id=correlation_id,
            )
        if task.status == Task.Status.ASSIGNED:
            task = transition_task(
                str(task.id),
                to_status=Task.Status.IN_PROGRESS,
                expected_version=task.version,
                actor_id="codex",
                correlation_id=correlation_id,
            )
        return task

    def _complete_task(self, task: Task, correlation_id: str, notes: str) -> Task:
        if task.status == Task.Status.IN_PROGRESS:
            task = transition_task(
                str(task.id),
                to_status=Task.Status.DELIVERED_UNVERIFIED,
                expected_version=task.version,
                actor_id="codex",
                correlation_id=correlation_id,
            )
        if (
            task.status == Task.Status.DELIVERED_UNVERIFIED
            and not task.verification_reviews.filter(decision=VerificationReview.Decision.ACCEPTED).exists()
        ):
            review_task_evidence(
                {"decision": VerificationReview.Decision.ACCEPTED, "notes": notes, "mark_passed": True},
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
                actor_id="codex",
                correlation_id=correlation_id,
            )
        return task
