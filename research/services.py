from django.db import transaction

from governance.models import AuditEvent
from operations.models import Task
from portfolio.models import Project, ProjectConnection
from research.models import ResearchTaskContract


class ResearchContractError(Exception):
    code = "RESEARCH_CONTRACT_ERROR"


class InvalidResearchContractPayloadError(ResearchContractError):
    code = "INVALID_RESEARCH_CONTRACT_PAYLOAD"


class ResearchContractBlockedError(ResearchContractError):
    code = "RESEARCH_CONTRACT_BLOCKED"


def serialize_research_contract(contract: ResearchTaskContract) -> dict:
    return {
        "id": str(contract.id),
        "task_id": str(contract.task_id),
        "project_id": str(contract.project_id),
        "project_connection_id": contract.project_connection_id,
        "title": contract.title,
        "original_request": contract.original_request,
        "research_question": contract.research_question,
        "scope": contract.scope,
        "deliverables": contract.deliverables,
        "budgets": contract.budgets,
        "safety_mode": contract.safety_mode,
        "depth_mode": contract.depth_mode,
        "status": contract.status,
        "created_by": contract.created_by,
        "created_at": contract.created_at.isoformat(),
    }


def research_adapter_status(*, project_id: str = "") -> dict:
    projects = Project.objects.order_by("slug")
    if project_id:
        projects = projects.filter(id=project_id)

    project_statuses = []
    for project in projects:
        connections = list(
            ProjectConnection.objects.filter(project=project, adapter_type__in=["research_manager", "research_manager_read_only"]).order_by("id")
        )
        contract_count = ResearchTaskContract.objects.filter(project=project).count()
        project_statuses.append(
            {
                "project_id": str(project.id),
                "slug": project.slug,
                "name": project.name,
                "repository_reference": project.repository_reference,
                "connections": [
                    {
                        "id": connection.id,
                        "adapter_type": connection.adapter_type,
                        "permission_mode": connection.permission_mode,
                        "active": connection.active,
                        "contract_version": connection.contract_version,
                        "capabilities": connection.capabilities,
                    }
                    for connection in connections
                ],
                "research_contracts": contract_count,
            }
        )

    return {
        "adapter": "research_manager_read_only",
        "external_execution_enabled": False,
        "external_status_checked": False,
        "projects": project_statuses,
    }


def create_research_contract(payload: dict, *, actor_id: str, correlation_id: str) -> ResearchTaskContract:
    task_id = str(payload.get("task_id", "")).strip()
    project_id = str(payload.get("project_id", "")).strip()
    project_connection_id = payload.get("project_connection_id")
    title = str(payload.get("title", "")).strip()
    original_request = str(payload.get("original_request", "")).strip()
    research_question = str(payload.get("research_question", "")).strip()
    scope = payload.get("scope", {})
    deliverables = payload.get("deliverables", [])
    budgets = payload.get("budgets", {})
    depth_mode = str(payload.get("depth_mode", ResearchTaskContract.DepthMode.DEEP)).strip()
    safety_mode = str(payload.get("safety_mode", "STRICT_MEDICAL")).strip()

    if not task_id or not project_id or not title or not original_request or not research_question:
        raise InvalidResearchContractPayloadError("task_id, project_id, title, original_request and research_question are required.")
    if not isinstance(scope, dict):
        raise InvalidResearchContractPayloadError("scope must be an object.")
    if not isinstance(deliverables, list):
        raise InvalidResearchContractPayloadError("deliverables must be a list.")
    if not isinstance(budgets, dict):
        raise InvalidResearchContractPayloadError("budgets must be an object.")
    if depth_mode not in ResearchTaskContract.DepthMode.values:
        raise InvalidResearchContractPayloadError("depth_mode must be QUICK, STANDARD, DEEP or SYSTEMATIC.")

    actor = actor_id.strip() or "api"
    with transaction.atomic():
        task = Task.objects.select_for_update().get(id=task_id)
        project = Project.objects.select_for_update().get(id=project_id)
        if task.status not in {Task.Status.APPROVED, Task.Status.ASSIGNED, Task.Status.IN_PROGRESS}:
            raise ResearchContractBlockedError("Research contracts require an approved or active Sharons task.")

        connections = ProjectConnection.objects.select_for_update().filter(
            project=project,
            active=True,
            permission_mode=ProjectConnection.PermissionMode.READ_ONLY,
        )
        if project_connection_id:
            connection = connections.get(id=int(project_connection_id))
        else:
            connection = connections.filter(adapter_type__in=["research_manager", "research_manager_read_only"]).first()
            if connection is None:
                connection = connections.first()
        if connection is None:
            raise ResearchContractBlockedError("A read-only active project connection is required.")

        contract = ResearchTaskContract.objects.create(
            task=task,
            project=project,
            project_connection=connection,
            title=title,
            original_request=original_request,
            research_question=research_question,
            scope=scope,
            deliverables=deliverables,
            budgets=budgets,
            safety_mode=safety_mode,
            depth_mode=depth_mode,
            status=ResearchTaskContract.Status.READY,
            created_by=actor,
        )
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="research.contract.created",
            object_type="research.ResearchTaskContract",
            object_id=str(contract.id),
            correlation_id=correlation_id,
            metadata={
                "task_id": str(task.id),
                "project_id": str(project.id),
                "project_connection_id": connection.id,
                "depth_mode": contract.depth_mode,
                "no_external_execution": True,
            },
        )
    return contract
