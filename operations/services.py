from django.db import models, transaction
from django.utils import timezone

from governance.models import AuditEvent
from operations.models import AcceptanceCriterion, AgentDefinition, AgentRun, Evidence, Plan, Task
from portfolio.models import Objective


class TaskTransitionError(Exception):
    code = "TASK_TRANSITION_ERROR"


class InvalidTaskTransitionError(TaskTransitionError):
    code = "INVALID_TASK_TRANSITION"


class TaskVersionConflictError(TaskTransitionError):
    code = "TASK_VERSION_CONFLICT"


class TaskVerificationIncompleteError(TaskTransitionError):
    code = "TASK_VERIFICATION_INCOMPLETE"


class TaskUpsertError(Exception):
    code = "TASK_UPSERT_ERROR"


class InvalidTaskUpsertPayloadError(TaskUpsertError):
    code = "INVALID_TASK_UPSERT_PAYLOAD"


class EvidenceRecordError(Exception):
    code = "EVIDENCE_RECORD_ERROR"


class InvalidEvidencePayloadError(EvidenceRecordError):
    code = "INVALID_EVIDENCE_PAYLOAD"


class TaskVerifyError(Exception):
    code = "TASK_VERIFY_ERROR"


class InvalidTaskVerifyPayloadError(TaskVerifyError):
    code = "INVALID_TASK_VERIFY_PAYLOAD"


class TaskVerifyBlockedError(TaskVerifyError):
    code = "TASK_VERIFY_BLOCKED"


class TaskAssignError(Exception):
    code = "TASK_ASSIGN_ERROR"


class InvalidTaskAssignPayloadError(TaskAssignError):
    code = "INVALID_TASK_ASSIGN_PAYLOAD"


class TaskAssignBlockedError(TaskAssignError):
    code = "TASK_ASSIGN_BLOCKED"


class AgentInvokeError(Exception):
    code = "AGENT_INVOKE_ERROR"


class InvalidAgentInvokePayloadError(AgentInvokeError):
    code = "INVALID_AGENT_INVOKE_PAYLOAD"


class AgentInvokeBlockedError(AgentInvokeError):
    code = "AGENT_INVOKE_BLOCKED"


class PlanCreateError(Exception):
    code = "PLAN_CREATE_ERROR"


class InvalidPlanPayloadError(PlanCreateError):
    code = "INVALID_PLAN_PAYLOAD"


CORE_AGENT_DEFINITIONS = [
    {
        "agent_id": "product_manager",
        "role": "Product Manager",
        "capabilities": ["product", "requirements", "user_research", "prioritization", "roadmap"],
        "tools": ["project_registry", "task_registry", "memory"],
        "allowed_data_classes": ["PUBLIC", "INTERNAL", "CONFIDENTIAL"],
        "forbidden_actions": ["external_publish", "contact_person", "spend_money", "production_change", "legal_commitment"],
        "max_risk_level": AgentDefinition.RiskLevel.MEDIUM,
        "max_concurrent_tasks": 2,
        "prompt_version": "core-agents-v1",
    },
    {
        "agent_id": "project_manager",
        "role": "Project Manager",
        "capabilities": ["project_management", "planning", "coordination", "status_reporting", "risk_tracking"],
        "tools": ["task_registry", "audit_log", "weekly_review"],
        "allowed_data_classes": ["PUBLIC", "INTERNAL", "CONFIDENTIAL"],
        "forbidden_actions": ["external_publish", "contact_person", "spend_money", "production_change", "legal_commitment"],
        "max_risk_level": AgentDefinition.RiskLevel.MEDIUM,
        "max_concurrent_tasks": 3,
        "prompt_version": "core-agents-v1",
    },
    {
        "agent_id": "executive_assistant",
        "role": "Executive Assistant",
        "capabilities": ["administration", "scheduling", "inbox_triage", "follow_up", "weekly_review_prep"],
        "tools": ["mailbox_mock", "task_registry", "memory"],
        "allowed_data_classes": ["PUBLIC", "INTERNAL", "CONFIDENTIAL"],
        "forbidden_actions": ["send_email", "contact_person", "spend_money", "production_change", "legal_commitment"],
        "max_risk_level": AgentDefinition.RiskLevel.LOW,
        "max_concurrent_tasks": 3,
        "prompt_version": "core-agents-v1",
    },
    {
        "agent_id": "developer",
        "role": "Developer",
        "capabilities": ["engineering", "implementation", "testing", "documentation", "code_review"],
        "tools": ["task_registry", "project_registry", "test_runner"],
        "allowed_data_classes": ["PUBLIC", "INTERNAL", "CONFIDENTIAL"],
        "forbidden_actions": ["production_deploy", "merge_without_approval", "spend_money", "contact_person", "legal_commitment"],
        "max_risk_level": AgentDefinition.RiskLevel.MEDIUM,
        "max_concurrent_tasks": 2,
        "prompt_version": "core-agents-v1",
    },
    {
        "agent_id": "marketing",
        "role": "Marketing",
        "capabilities": ["marketing", "positioning", "copywriting", "campaign_planning", "audience_research"],
        "tools": ["task_registry", "memory", "project_registry"],
        "allowed_data_classes": ["PUBLIC", "INTERNAL"],
        "forbidden_actions": ["external_publish", "contact_person", "spend_money", "production_change", "legal_commitment"],
        "max_risk_level": AgentDefinition.RiskLevel.LOW,
        "max_concurrent_tasks": 2,
        "prompt_version": "core-agents-v1",
    },
]


ALLOWED_TRANSITIONS = {
    Task.Status.DRAFT: {Task.Status.PLANNED, Task.Status.CANCELLED},
    Task.Status.PLANNED: {Task.Status.PENDING_APPROVAL, Task.Status.APPROVED, Task.Status.CANCELLED},
    Task.Status.PENDING_APPROVAL: {Task.Status.APPROVED, Task.Status.BLOCKED, Task.Status.CANCELLED},
    Task.Status.APPROVED: {Task.Status.ASSIGNED, Task.Status.CANCELLED},
    Task.Status.ASSIGNED: {Task.Status.IN_PROGRESS, Task.Status.BLOCKED, Task.Status.CANCELLED},
    Task.Status.IN_PROGRESS: {
        Task.Status.BLOCKED,
        Task.Status.DELIVERED_UNVERIFIED,
        Task.Status.VERIFYING,
        Task.Status.FAILED,
        Task.Status.CANCELLED,
    },
    Task.Status.BLOCKED: {Task.Status.PLANNED, Task.Status.ASSIGNED, Task.Status.IN_PROGRESS, Task.Status.CANCELLED},
    Task.Status.DELIVERED_UNVERIFIED: {Task.Status.VERIFYING, Task.Status.IN_PROGRESS, Task.Status.CANCELLED},
    Task.Status.VERIFYING: {Task.Status.COMPLETED, Task.Status.DELIVERED_UNVERIFIED, Task.Status.IN_PROGRESS, Task.Status.FAILED},
    Task.Status.COMPLETED: set(),
    Task.Status.FAILED: set(),
    Task.Status.CANCELLED: set(),
}

TERMINAL_TASK_STATUSES = {Task.Status.COMPLETED, Task.Status.FAILED, Task.Status.CANCELLED}


def seed_core_agents(*, actor_id: str, correlation_id: str) -> list[AgentDefinition]:
    actor = actor_id.strip() or "api"
    correlation = correlation_id.strip()
    if not correlation:
        raise ValueError("correlation_id is required.")

    agents: list[AgentDefinition] = []
    with transaction.atomic():
        for definition in CORE_AGENT_DEFINITIONS:
            agent, _created = AgentDefinition.objects.update_or_create(
                agent_id=definition["agent_id"],
                defaults={
                    "role": definition["role"],
                    "capabilities": definition["capabilities"],
                    "tools": definition["tools"],
                    "allowed_data_classes": definition["allowed_data_classes"],
                    "forbidden_actions": definition["forbidden_actions"],
                    "max_risk_level": definition["max_risk_level"],
                    "max_concurrent_tasks": definition["max_concurrent_tasks"],
                    "prompt_version": definition["prompt_version"],
                    "active": True,
                },
            )
            agents.append(agent)

        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="operations.core_agents.seeded",
            object_type="operations.AgentDefinition",
            object_id="core_agents",
            correlation_id=correlation,
            metadata={"agent_ids": [agent.agent_id for agent in agents], "count": len(agents)},
        )
    return agents


def list_tasks_for_dashboard(*, status: str = "", objective_id: str = "", owner_agent_id: str = "", limit: int = 100) -> list[Task]:
    tasks = Task.objects.select_related("objective", "plan").order_by("-updated_at")
    if status:
        tasks = tasks.filter(status=status)
    if objective_id:
        tasks = tasks.filter(objective_id=objective_id)
    if owner_agent_id:
        tasks = tasks.filter(owner_agent_id=owner_agent_id)
    return list(tasks[:limit])


def task_detail_context(task_id: str) -> dict:
    task = Task.objects.select_related("objective", "plan").get(id=task_id)
    return {
        "task": task,
        "acceptance_criteria": list(task.acceptance_criteria.order_by("id")),
        "evidence_records": list(task.evidence.order_by("-created_at")),
        "agent_runs": list(task.agent_runs.order_by("-started_at")),
        "audit_events": list(AuditEvent.objects.filter(object_type="operations.Task", object_id=str(task.id))[:20]),
    }


def transition_task(
    task_id: str,
    *,
    to_status: str,
    expected_version: int,
    actor_id: str,
    correlation_id: str,
) -> Task:
    actor_id = actor_id.strip() or "api"
    correlation_id = correlation_id.strip()
    if not correlation_id:
        raise InvalidTaskTransitionError("correlation_id is required.")

    with transaction.atomic():
        task = Task.objects.select_for_update().get(id=task_id)
        if task.version != expected_version:
            raise TaskVersionConflictError("Task version does not match expected_version.")

        allowed = ALLOWED_TRANSITIONS[task.status]
        if to_status not in allowed:
            raise InvalidTaskTransitionError(f"Cannot transition task from {task.status} to {to_status}.")

        if to_status == Task.Status.COMPLETED:
            required_criteria = task.acceptance_criteria.filter(required=True)
            if not required_criteria.exists():
                raise TaskVerificationIncompleteError("At least one required acceptance criterion must exist before completion.")
            if required_criteria.exclude(status=AcceptanceCriterion.Status.PASSED).exists():
                raise TaskVerificationIncompleteError("All required acceptance criteria must pass before completion.")

        before_status = task.status
        before_version = task.version
        task.status = to_status
        task.version += 1
        task.save(update_fields=["status", "version", "updated_at"])

        released_agent_id = ""
        if to_status in TERMINAL_TASK_STATUSES and before_status not in TERMINAL_TASK_STATUSES and task.owner_agent_id:
            updated = AgentDefinition.objects.select_for_update().filter(
                agent_id=task.owner_agent_id,
                current_task_count__gt=0,
            ).update(current_task_count=models.F("current_task_count") - 1)
            if updated:
                released_agent_id = task.owner_agent_id

        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor_id,
            action="operations.task.transitioned",
            object_type="operations.Task",
            object_id=str(task.id),
            correlation_id=correlation_id,
            metadata={
                "from_status": before_status,
                "to_status": task.status,
                "from_version": before_version,
                "to_version": task.version,
                "released_agent_id": released_agent_id,
            },
        )

    return task


def serialize_task(task: Task) -> dict:
    return {
        "id": str(task.id),
        "objective_id": str(task.objective_id),
        "plan_id": str(task.plan_id) if task.plan_id else None,
        "external_key": task.external_key,
        "title": task.title,
        "business_outcome": task.business_outcome,
        "owner_agent_id": task.owner_agent_id,
        "status": task.status,
        "version": task.version,
        "acceptance_criteria": [
            {
                "id": str(criterion.id),
                "description": criterion.description,
                "criterion_type": criterion.criterion_type,
                "required": criterion.required,
                "status": criterion.status,
            }
            for criterion in task.acceptance_criteria.order_by("id")
        ],
    }


def serialize_evidence(evidence: Evidence) -> dict:
    return {
        "id": str(evidence.id),
        "task_id": str(evidence.task_id),
        "kind": evidence.kind,
        "uri_or_reference": evidence.uri_or_reference,
        "checksum": evidence.checksum,
        "metadata": evidence.metadata,
        "verified": evidence.verified,
        "created_by": evidence.created_by,
    }


def serialize_agent(agent: AgentDefinition) -> dict:
    return {
        "agent_id": agent.agent_id,
        "role": agent.role,
        "capabilities": agent.capabilities,
        "tools": agent.tools,
        "allowed_data_classes": agent.allowed_data_classes,
        "forbidden_actions": agent.forbidden_actions,
        "max_risk_level": agent.max_risk_level,
        "max_concurrent_tasks": agent.max_concurrent_tasks,
        "current_task_count": agent.current_task_count,
        "reliability_score": str(agent.reliability_score),
        "prompt_version": agent.prompt_version,
        "active": agent.active,
        "available_capacity": max(0, agent.max_concurrent_tasks - agent.current_task_count),
    }


def serialize_agent_run(agent_run: AgentRun) -> dict:
    return {
        "id": str(agent_run.id),
        "task_id": str(agent_run.task_id),
        "agent_id": agent_run.agent_id,
        "attempt_number": agent_run.attempt_number,
        "status": agent_run.status,
        "input_snapshot": agent_run.input_snapshot,
        "output": agent_run.output,
        "token_or_cost_metadata": agent_run.token_or_cost_metadata,
        "correlation_id": agent_run.correlation_id,
        "started_at": agent_run.started_at.isoformat() if agent_run.started_at else None,
        "completed_at": agent_run.completed_at.isoformat() if agent_run.completed_at else None,
    }


def serialize_plan(plan: Plan) -> dict:
    return {
        "id": str(plan.id),
        "objective_id": str(plan.objective_id),
        "name": plan.name,
        "version": plan.version,
        "status": plan.status,
        "assumptions": plan.assumptions,
        "risks": plan.risks,
        "created_by": plan.created_by,
        "approved_by": plan.approved_by,
        "created_at": plan.created_at.isoformat(),
    }


def create_plan(payload: dict, *, actor_id: str, correlation_id: str) -> Plan:
    objective_id = str(payload.get("objective_id", "")).strip()
    name = str(payload.get("name", "")).strip()
    assumptions = payload.get("assumptions", {})
    risks = payload.get("risks", {})
    if not objective_id or not name:
        raise InvalidPlanPayloadError("objective_id and name are required.")
    if not isinstance(assumptions, dict):
        raise InvalidPlanPayloadError("assumptions must be an object.")
    if not isinstance(risks, dict):
        raise InvalidPlanPayloadError("risks must be an object.")

    actor = actor_id.strip() or "api"
    with transaction.atomic():
        objective = Objective.objects.select_for_update().get(id=objective_id, status=Objective.Status.ACTIVE)
        existing_versions = Plan.objects.select_for_update().filter(objective=objective, name=name).count()
        plan = Plan.objects.create(
            objective=objective,
            name=name,
            version=existing_versions + 1,
            status=Plan.Status.DRAFT,
            assumptions=assumptions,
            risks=risks,
            created_by=actor,
        )
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="operations.plan.created",
            object_type="operations.Plan",
            object_id=str(plan.id),
            correlation_id=correlation_id,
            metadata={"objective_id": str(objective.id), "name": plan.name, "version": plan.version},
        )
    return plan


def agent_performance(agent_id: str) -> dict:
    agent = AgentDefinition.objects.get(agent_id=agent_id)
    runs = AgentRun.objects.filter(agent_id=agent.agent_id)
    assigned_tasks = Task.objects.filter(owner_agent_id=agent.agent_id)
    completed_runs = runs.filter(status=AgentRun.Status.COMPLETED).count()
    failed_runs = runs.filter(status=AgentRun.Status.FAILED).count()
    started_runs = runs.filter(status=AgentRun.Status.STARTED).count()
    total_runs = runs.count()
    completed_tasks = assigned_tasks.filter(status=Task.Status.COMPLETED).count()
    active_tasks = assigned_tasks.exclude(status__in=[Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.FAILED]).count()
    return {
        "agent": serialize_agent(agent),
        "runs": {
            "total": total_runs,
            "started": started_runs,
            "completed": completed_runs,
            "failed": failed_runs,
        },
        "tasks": {
            "assigned_total": assigned_tasks.count(),
            "active": active_tasks,
            "completed": completed_tasks,
        },
        "reliability_score": str(agent.reliability_score),
    }


def list_available_agents(*, capability: str = "", data_class: str = "", max_risk_level: int | None = None) -> list[AgentDefinition]:
    agents = AgentDefinition.objects.filter(active=True).order_by("agent_id")
    if capability:
        agents = agents.filter(capabilities__contains=[capability])
    if data_class:
        agents = agents.filter(allowed_data_classes__contains=[data_class])
    if max_risk_level is not None:
        agents = agents.filter(max_risk_level__gte=max_risk_level)
    return [agent for agent in agents if agent.current_task_count < agent.max_concurrent_tasks]


def invoke_agent(payload: dict, *, actor_id: str, correlation_id: str) -> AgentRun:
    task_id = str(payload.get("task_id", "")).strip()
    agent_id = str(payload.get("agent_id", "")).strip()
    input_snapshot = payload.get("input_snapshot", {})
    if not task_id or not agent_id:
        raise InvalidAgentInvokePayloadError("task_id and agent_id are required.")
    if not isinstance(input_snapshot, dict):
        raise InvalidAgentInvokePayloadError("input_snapshot must be an object.")

    actor = actor_id.strip() or "api"
    with transaction.atomic():
        task = Task.objects.select_for_update().get(id=task_id)
        if task.owner_agent_id != agent_id:
            raise AgentInvokeBlockedError("Task is not assigned to the requested agent.")
        if task.status not in {Task.Status.ASSIGNED, Task.Status.IN_PROGRESS}:
            raise AgentInvokeBlockedError("Task must be ASSIGNED or IN_PROGRESS before agent invocation.")

        agent = AgentDefinition.objects.select_for_update().get(agent_id=agent_id)
        if not agent.active:
            raise AgentInvokeBlockedError("Agent is inactive.")

        previous_attempts = AgentRun.objects.select_for_update().filter(task=task, agent_id=agent_id).count()
        if previous_attempts >= 2:
            raise AgentInvokeBlockedError("Agent invocation is capped at two attempts for a task.")

        agent_run = AgentRun.objects.create(
            task=task,
            agent_id=agent.agent_id,
            attempt_number=previous_attempts + 1,
            status=AgentRun.Status.STARTED,
            input_snapshot=input_snapshot,
            correlation_id=correlation_id,
        )
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="operations.agent_run.started",
            object_type="operations.AgentRun",
            object_id=str(agent_run.id),
            correlation_id=correlation_id,
            metadata={
                "task_id": str(task.id),
                "agent_id": agent.agent_id,
                "attempt_number": agent_run.attempt_number,
                "no_external_execution": True,
            },
        )
    return agent_run


def assign_task(payload: dict, *, task_id: str, actor_id: str, correlation_id: str) -> Task:
    agent_id = str(payload.get("agent_id", "")).strip()
    if not agent_id:
        raise InvalidTaskAssignPayloadError("agent_id is required.")
    try:
        expected_version = int(payload["expected_version"])
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidTaskAssignPayloadError("expected_version is required and must be an integer.") from exc

    actor = actor_id.strip() or "api"
    with transaction.atomic():
        task = Task.objects.select_for_update().get(id=task_id)
        if task.version != expected_version:
            raise TaskVersionConflictError("Task version does not match expected_version.")
        if task.status != Task.Status.APPROVED:
            raise TaskAssignBlockedError("Only APPROVED tasks can be assigned.")

        agent = AgentDefinition.objects.select_for_update().get(agent_id=agent_id)
        if not agent.active:
            raise TaskAssignBlockedError("Agent is inactive.")
        if agent.current_task_count >= agent.max_concurrent_tasks:
            raise TaskAssignBlockedError("Agent has no available capacity.")

        before_status = task.status
        before_version = task.version
        task.owner_agent_id = agent.agent_id
        task.status = Task.Status.ASSIGNED
        task.version += 1
        task.save(update_fields=["owner_agent_id", "status", "version", "updated_at"])

        agent.current_task_count += 1
        agent.save(update_fields=["current_task_count"])

        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="operations.task.assigned",
            object_type="operations.Task",
            object_id=str(task.id),
            correlation_id=correlation_id,
            metadata={
                "agent_id": agent.agent_id,
                "from_status": before_status,
                "to_status": task.status,
                "from_version": before_version,
                "to_version": task.version,
            },
        )
    return task


def record_task_evidence(payload: dict, *, task_id: str, actor_id: str, correlation_id: str) -> Evidence:
    kind = str(payload.get("kind", "")).strip()
    uri_or_reference = str(payload.get("uri_or_reference", "")).strip()
    checksum = str(payload.get("checksum", "")).strip()
    metadata = payload.get("metadata", {})
    verified = bool(payload.get("verified", False))

    if kind not in Evidence.Kind.values:
        raise InvalidEvidencePayloadError("kind is required and must be a valid evidence kind.")
    if not uri_or_reference:
        raise InvalidEvidencePayloadError("uri_or_reference is required.")
    if not isinstance(metadata, dict):
        raise InvalidEvidencePayloadError("metadata must be an object.")

    actor = actor_id.strip() or "api"
    with transaction.atomic():
        task = Task.objects.select_for_update().get(id=task_id)
        evidence = Evidence.objects.create(
            task=task,
            kind=kind,
            uri_or_reference=uri_or_reference,
            checksum=checksum,
            metadata=metadata,
            verified=verified,
            created_by=actor,
        )
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="operations.task.evidence_recorded",
            object_type="operations.Evidence",
            object_id=str(evidence.id),
            correlation_id=correlation_id,
            metadata={
                "task_id": str(task.id),
                "kind": evidence.kind,
                "verified": evidence.verified,
            },
        )
    return evidence


def verify_task(payload: dict, *, task_id: str, actor_id: str, correlation_id: str) -> Task:
    mark_passed = bool(payload.get("mark_passed", False))
    actor = actor_id.strip() or "api"
    if payload.get("notes") is not None and not isinstance(payload["notes"], str):
        raise InvalidTaskVerifyPayloadError("notes must be a string when provided.")

    with transaction.atomic():
        task = Task.objects.select_for_update().get(id=task_id)
        required_criteria = list(task.acceptance_criteria.select_for_update().filter(required=True))
        if not required_criteria:
            raise TaskVerifyBlockedError("At least one required acceptance criterion is required for verification.")

        verified_evidence_exists = task.evidence.filter(verified=True).exists()
        if not verified_evidence_exists:
            raise TaskVerifyBlockedError("At least one verified evidence record is required for verification.")

        passed_count = 0
        if mark_passed:
            for criterion in required_criteria:
                criterion.status = AcceptanceCriterion.Status.PASSED
                criterion.verified_by = actor
                criterion.verified_at = timezone.now()
                criterion.save(update_fields=["status", "verified_by", "verified_at"])
                passed_count += 1

        before_status = task.status
        before_version = task.version
        if task.status == Task.Status.DELIVERED_UNVERIFIED:
            task.status = Task.Status.VERIFYING
            task.version += 1
            task.save(update_fields=["status", "version", "updated_at"])

        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="operations.task.verified",
            object_type="operations.Task",
            object_id=str(task.id),
            correlation_id=correlation_id,
            metadata={
                "from_status": before_status,
                "to_status": task.status,
                "from_version": before_version,
                "to_version": task.version,
                "required_criteria": len(required_criteria),
                "criteria_marked_passed": passed_count,
                "verified_evidence_count": task.evidence.filter(verified=True).count(),
                "notes": str(payload.get("notes", "")).strip(),
            },
        )
    return task


def upsert_task(payload: dict, *, actor_id: str, correlation_id: str) -> tuple[Task, bool]:
    title = str(payload.get("title", "")).strip()
    objective_id = str(payload.get("objective_id", "")).strip()
    external_key = str(payload.get("external_key", "")).strip()
    if not title or not objective_id:
        raise InvalidTaskUpsertPayloadError("title and objective_id are required.")

    criteria_payload = payload.get("acceptance_criteria", [])
    if not isinstance(criteria_payload, list):
        raise InvalidTaskUpsertPayloadError("acceptance_criteria must be a list.")
    cleaned_criteria = []
    for item in criteria_payload:
        if not isinstance(item, dict):
            raise InvalidTaskUpsertPayloadError("Each acceptance criterion must be an object.")
        description = str(item.get("description", "")).strip()
        if not description:
            raise InvalidTaskUpsertPayloadError("Acceptance criterion description cannot be empty.")
        criterion_type = str(item.get("criterion_type", AcceptanceCriterion.CriterionType.MANUAL)).strip()
        if criterion_type not in AcceptanceCriterion.CriterionType.values:
            raise InvalidTaskUpsertPayloadError("Acceptance criterion type is invalid.")
        cleaned_criteria.append(
            {
                "description": description,
                "criterion_type": criterion_type,
                "required": bool(item.get("required", True)),
            }
        )

    with transaction.atomic():
        objective = Objective.objects.select_for_update().get(id=objective_id, status=Objective.Status.ACTIVE)
        plan = None
        plan_id = str(payload.get("plan_id", "")).strip()
        if plan_id:
            plan = Plan.objects.select_for_update().get(id=plan_id, objective=objective)

        created = False
        if external_key:
            task, created = Task.objects.select_for_update().get_or_create(
                objective=objective,
                external_key=external_key,
                defaults={
                    "plan": plan,
                    "title": title,
                    "business_outcome": str(payload.get("business_outcome", "")).strip(),
                    "status": Task.Status.DRAFT,
                    "created_by": actor_id.strip() or "api",
                },
            )
        else:
            task = Task.objects.create(
                objective=objective,
                plan=plan,
                title=title,
                business_outcome=str(payload.get("business_outcome", "")).strip(),
                status=Task.Status.DRAFT,
                created_by=actor_id.strip() or "api",
            )
            created = True

        if not created:
            task.plan = plan
            task.title = title
            task.business_outcome = str(payload.get("business_outcome", "")).strip()
            task.version += 1
            task.save(update_fields=["plan", "title", "business_outcome", "version", "updated_at"])

        if cleaned_criteria:
            task.acceptance_criteria.all().delete()
            AcceptanceCriterion.objects.bulk_create(
                [
                    AcceptanceCriterion(
                        task=task,
                        description=item["description"],
                        criterion_type=item["criterion_type"],
                        required=item["required"],
                    )
                    for item in cleaned_criteria
                ]
            )

        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor_id.strip() or "api",
            action="operations.task.upserted",
            object_type="operations.Task",
            object_id=str(task.id),
            correlation_id=correlation_id,
            metadata={"created": created, "objective_id": str(objective.id), "external_key": task.external_key},
        )
    return task, created
