from django.db import transaction

from developer.models import DeveloperWorkContract, ImplementationPlan
from governance.models import AuditEvent
from operations.models import AgentDefinition, Evidence, Task
from operations.services import record_task_evidence, transition_task
from portfolio.models import Project, ProjectConnection


class DeveloperError(Exception):
    code = "DEVELOPER_ERROR"


class InvalidDeveloperPayloadError(DeveloperError):
    code = "INVALID_DEVELOPER_PAYLOAD"


class DeveloperBlockedError(DeveloperError):
    code = "DEVELOPER_BLOCKED"


def serialize_developer_work_contract(contract: DeveloperWorkContract) -> dict:
    return {
        "id": str(contract.id),
        "task_id": str(contract.task_id),
        "project_id": str(contract.project_id),
        "project_connection_id": contract.project_connection_id,
        "title": contract.title,
        "objective": contract.objective,
        "scope": contract.scope,
        "constraints": contract.constraints,
        "acceptance_focus": contract.acceptance_focus,
        "status": contract.status,
        "no_repo_write": contract.no_repo_write,
        "no_deploy": contract.no_deploy,
        "created_by": contract.created_by,
        "created_at": contract.created_at.isoformat(),
    }


def serialize_implementation_plan(plan: ImplementationPlan) -> dict:
    return {
        "id": str(plan.id),
        "contract_id": str(plan.contract_id),
        "title": plan.title,
        "summary": plan.summary,
        "planned_changes": plan.planned_changes,
        "verification_plan": plan.verification_plan,
        "risks": plan.risks,
        "evidence": plan.evidence,
        "status": plan.status,
        "no_repo_write": plan.no_repo_write,
        "no_deploy": plan.no_deploy,
        "created_by": plan.created_by,
        "created_at": plan.created_at.isoformat(),
    }


def developer_status(*, project_id: str = "") -> dict:
    contracts = DeveloperWorkContract.objects.all()
    plans = ImplementationPlan.objects.all()
    if project_id:
        contracts = contracts.filter(project_id=project_id)
        plans = plans.filter(contract__project_id=project_id)
    return {
        "agent_id": "developer",
        "agent_registered": AgentDefinition.objects.filter(agent_id="developer", active=True).exists(),
        "repo_write_enabled": False,
        "deploy_enabled": False,
        "work_contracts": contracts.count(),
        "implementation_plans": plans.count(),
        "delivered_unverified": plans.filter(status=ImplementationPlan.Status.DELIVERED_UNVERIFIED).count(),
    }


def create_developer_work_contract(payload: dict, *, actor_id: str, correlation_id: str) -> DeveloperWorkContract:
    task_id = str(payload.get("task_id", "")).strip()
    project_id = str(payload.get("project_id", "")).strip()
    project_connection_id = payload.get("project_connection_id")
    title = str(payload.get("title", "")).strip()
    objective = str(payload.get("objective", "")).strip()
    scope = payload.get("scope", [])
    constraints = payload.get("constraints", {})
    acceptance_focus = payload.get("acceptance_focus", [])

    if not task_id or not project_id or not title or not objective:
        raise InvalidDeveloperPayloadError("task_id, project_id, title and objective are required.")
    if not isinstance(scope, list):
        raise InvalidDeveloperPayloadError("scope must be a list.")
    if not isinstance(constraints, dict):
        raise InvalidDeveloperPayloadError("constraints must be an object.")
    if not isinstance(acceptance_focus, list):
        raise InvalidDeveloperPayloadError("acceptance_focus must be a list.")

    actor = actor_id.strip() or "api"
    with transaction.atomic():
        task = Task.objects.select_for_update().get(id=task_id)
        project = Project.objects.select_for_update().get(id=project_id)
        if task.status not in {Task.Status.APPROVED, Task.Status.ASSIGNED, Task.Status.IN_PROGRESS}:
            raise DeveloperBlockedError("Developer work contracts require an approved or active task.")

        connections = ProjectConnection.objects.select_for_update().filter(
            project=project,
            active=True,
            permission_mode=ProjectConnection.PermissionMode.READ_ONLY,
        )
        if project_connection_id:
            connection = connections.get(id=int(project_connection_id))
        else:
            connection = connections.filter(adapter_type__in=["developer_read_only", "local_repository", "repository_read_only"]).first() or connections.first()
        if connection is None:
            raise DeveloperBlockedError("A read-only active project connection is required.")

        contract = DeveloperWorkContract.objects.create(
            task=task,
            project=project,
            project_connection=connection,
            title=title,
            objective=objective,
            scope=scope,
            constraints=constraints,
            acceptance_focus=acceptance_focus,
            status=DeveloperWorkContract.Status.READY,
            no_repo_write=True,
            no_deploy=True,
            created_by=actor,
        )
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="developer.work_contract.created",
            object_type="developer.DeveloperWorkContract",
            object_id=str(contract.id),
            correlation_id=correlation_id,
            metadata={
                "task_id": str(task.id),
                "project_id": str(project.id),
                "project_connection_id": connection.id,
                "no_repo_write": True,
                "no_deploy": True,
            },
        )
    return contract


def create_implementation_plan(payload: dict, *, contract_id: str, actor_id: str, correlation_id: str) -> ImplementationPlan:
    title = str(payload.get("title", "")).strip()
    summary = str(payload.get("summary", "")).strip()
    planned_changes = payload.get("planned_changes", [])
    verification_plan = payload.get("verification_plan", [])
    risks = payload.get("risks", [])
    if not title or not summary:
        raise InvalidDeveloperPayloadError("title and summary are required.")
    if not isinstance(planned_changes, list) or not planned_changes:
        raise InvalidDeveloperPayloadError("planned_changes must be a non-empty list.")
    if not isinstance(verification_plan, list) or not verification_plan:
        raise InvalidDeveloperPayloadError("verification_plan must be a non-empty list.")
    if not isinstance(risks, list):
        raise InvalidDeveloperPayloadError("risks must be a list.")

    actor = actor_id.strip() or "api"
    with transaction.atomic():
        contract = DeveloperWorkContract.objects.select_for_update().get(id=contract_id)
        if contract.status not in {DeveloperWorkContract.Status.READY, DeveloperWorkContract.Status.IN_PROGRESS}:
            raise DeveloperBlockedError("Implementation plans require a ready or in-progress developer contract.")
        plan = ImplementationPlan.objects.create(
            contract=contract,
            title=title,
            summary=summary,
            planned_changes=planned_changes,
            verification_plan=verification_plan,
            risks=risks,
            status=ImplementationPlan.Status.NEEDS_REVIEW,
            no_repo_write=True,
            no_deploy=True,
            created_by=actor,
        )
        if contract.status == DeveloperWorkContract.Status.READY:
            contract.status = DeveloperWorkContract.Status.IN_PROGRESS
            contract.save(update_fields=["status"])
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="developer.implementation_plan.created",
            object_type="developer.ImplementationPlan",
            object_id=str(plan.id),
            correlation_id=correlation_id,
            metadata={"contract_id": str(contract.id), "no_repo_write": True, "no_deploy": True},
        )
    return plan


def deliver_implementation_plan(payload: dict, *, plan_id: str, actor_id: str, correlation_id: str) -> ImplementationPlan:
    evidence = payload.get("evidence", [])
    if not isinstance(evidence, list) or not evidence:
        raise InvalidDeveloperPayloadError("evidence must be a non-empty list.")

    actor = actor_id.strip() or "api"
    with transaction.atomic():
        plan = ImplementationPlan.objects.select_for_update().select_related("contract__task").get(id=plan_id)
        if plan.status not in {ImplementationPlan.Status.NEEDS_REVIEW, ImplementationPlan.Status.APPROVED}:
            raise DeveloperBlockedError("Only active implementation plans can be delivered.")
        task = plan.contract.task
        if task.status != Task.Status.IN_PROGRESS:
            raise DeveloperBlockedError("Task must be IN_PROGRESS before developer delivery.")

        recorded_evidence = []
        for index, item in enumerate(evidence):
            reference = str(item.get("uri_or_reference", item.get("reference", ""))).strip() if isinstance(item, dict) else str(item).strip()
            if not reference:
                raise InvalidDeveloperPayloadError("Every evidence item requires a reference.")
            record = record_task_evidence(
                {
                    "kind": Evidence.Kind.ARTIFACT,
                    "uri_or_reference": reference,
                    "metadata": {"source": "developer_agent", "implementation_plan_id": str(plan.id), "index": index},
                    "verified": False,
                },
                task_id=str(task.id),
                actor_id=actor,
                correlation_id=correlation_id,
            )
            recorded_evidence.append({"evidence_id": str(record.id), "uri_or_reference": record.uri_or_reference})

        transition_task(
            str(task.id),
            to_status=Task.Status.DELIVERED_UNVERIFIED,
            expected_version=task.version,
            actor_id=actor,
            correlation_id=correlation_id,
        )
        plan.evidence = recorded_evidence
        plan.status = ImplementationPlan.Status.DELIVERED_UNVERIFIED
        plan.save(update_fields=["evidence", "status"])
        contract = plan.contract
        contract.status = DeveloperWorkContract.Status.DELIVERED
        contract.save(update_fields=["status"])
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="developer.implementation_plan.delivered",
            object_type="developer.ImplementationPlan",
            object_id=str(plan.id),
            correlation_id=correlation_id,
            metadata={
                "task_id": str(task.id),
                "evidence_count": len(recorded_evidence),
                "task_status": Task.Status.DELIVERED_UNVERIFIED,
                "no_repo_write": True,
                "no_deploy": True,
            },
        )
    return plan

