from django.db import transaction

from governance.models import AuditEvent
from operations.models import AcceptanceCriterion, AgentDefinition, Task
from operations.services import upsert_task
from portfolio.models import Project, ProjectConnection
from product.models import ProductSpecContract, ProductSpecDraft


class ProductContractError(Exception):
    code = "PRODUCT_CONTRACT_ERROR"


class InvalidProductContractPayloadError(ProductContractError):
    code = "INVALID_PRODUCT_CONTRACT_PAYLOAD"


class ProductContractBlockedError(ProductContractError):
    code = "PRODUCT_CONTRACT_BLOCKED"


def serialize_product_spec_contract(contract: ProductSpecContract) -> dict:
    return {
        "id": str(contract.id),
        "task_id": str(contract.task_id),
        "project_id": str(contract.project_id),
        "project_connection_id": contract.project_connection_id,
        "title": contract.title,
        "spec_type": contract.spec_type,
        "objective": contract.objective,
        "target_users": contract.target_users,
        "problem_statement": contract.problem_statement,
        "success_metrics": contract.success_metrics,
        "requirements": contract.requirements,
        "constraints": contract.constraints,
        "open_questions": contract.open_questions,
        "deliverables": contract.deliverables,
        "status": contract.status,
        "no_external_write": contract.no_external_write,
        "created_by": contract.created_by,
        "created_at": contract.created_at.isoformat(),
    }


def serialize_product_spec_draft(draft: ProductSpecDraft) -> dict:
    return {
        "id": str(draft.id),
        "contract_id": str(draft.contract_id),
        "title": draft.title,
        "content": draft.content,
        "assumptions": draft.assumptions,
        "risks": draft.risks,
        "review_status": draft.review_status,
        "no_external_write": draft.no_external_write,
        "created_by": draft.created_by,
        "created_at": draft.created_at.isoformat(),
    }


def product_manager_status(*, project_id: str = "") -> dict:
    projects = Project.objects.all().order_by("id")
    if project_id:
        projects = projects.filter(id=project_id)

    project_statuses = []
    for project in projects:
        connections = list(
            ProjectConnection.objects.filter(project=project, adapter_type__in=["product_read_only", "product_manager_read_only"]).order_by("id")
        )
        contract_count = ProductSpecContract.objects.filter(project=project).count()
        draft_count = ProductSpecDraft.objects.filter(contract__project=project).count()
        project_statuses.append(
            {
                "project_id": str(project.id),
                "name": project.name,
                "status": project.status,
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
                "product_spec_contracts": contract_count,
                "product_spec_drafts": draft_count,
            }
        )

    return {
        "agent_id": "product_manager",
        "agent_registered": AgentDefinition.objects.filter(agent_id="product_manager", active=True).exists(),
        "adapter": "product_manager_read_only",
        "external_write_enabled": False,
        "external_status_checked": False,
        "projects": project_statuses,
    }


def _list_field(value) -> list:
    return value if isinstance(value, list) else []


def project_product_readiness(*, project_id: str) -> dict:
    project = Project.objects.get(id=project_id)
    contracts = ProductSpecContract.objects.filter(project=project)
    drafts = ProductSpecDraft.objects.filter(contract__project=project)
    approved_drafts = drafts.filter(review_status=ProductSpecDraft.ReviewStatus.APPROVED)
    open_questions = sum(len(_list_field(contract.open_questions)) for contract in contracts)
    ready_contracts = contracts.filter(status=ProductSpecContract.Status.READY).count()
    in_progress_contracts = contracts.filter(status=ProductSpecContract.Status.IN_PROGRESS).count()
    completed_contracts = contracts.filter(status=ProductSpecContract.Status.COMPLETED).count()

    blockers: list[str] = []
    if not contracts.exists():
        blockers.append("No product spec contracts exist for this project.")
    if contracts.exists() and not approved_drafts.exists():
        blockers.append("No approved product spec draft is ready for implementation planning.")
    if open_questions:
        blockers.append("One or more product contracts still have open questions.")

    if blockers:
        readiness_status = "BLOCKED" if not approved_drafts.exists() else "AT_RISK"
    else:
        readiness_status = "READY_FOR_IMPLEMENTATION"

    return {
        "project": project,
        "readiness_status": readiness_status,
        "blockers": blockers,
        "counts": {
            "contracts": contracts.count(),
            "ready_contracts": ready_contracts,
            "in_progress_contracts": in_progress_contracts,
            "completed_contracts": completed_contracts,
            "drafts": drafts.count(),
            "approved_drafts": approved_drafts.count(),
            "open_questions": open_questions,
        },
    }


def serialize_project_product_readiness(readiness: dict) -> dict:
    project = readiness["project"]
    return {
        "project": {
            "id": str(project.id),
            "name": project.name,
            "status": project.status,
            "repository_reference": project.repository_reference,
            "data_classification": project.data_classification,
        },
        "readiness_status": readiness["readiness_status"],
        "blockers": readiness["blockers"],
        "counts": readiness["counts"],
        "external_write_enabled": False,
    }


def product_project_roadmap(*, project_id: str) -> dict:
    project = Project.objects.get(id=project_id)
    contracts = ProductSpecContract.objects.filter(project=project).select_related("task", "task__objective").order_by("created_at")
    milestones = []
    open_questions = []
    for contract in contracts:
        approved_drafts = ProductSpecDraft.objects.filter(
            contract=contract,
            review_status=ProductSpecDraft.ReviewStatus.APPROVED,
        ).count()
        milestone_status = "READY_FOR_IMPLEMENTATION" if approved_drafts and not contract.open_questions else "NEEDS_PRODUCT_REVIEW"
        if contract.status in {ProductSpecContract.Status.COMPLETED, ProductSpecContract.Status.CANCELLED}:
            milestone_status = contract.status
        milestones.append(
            {
                "contract_id": str(contract.id),
                "objective_id": str(contract.task.objective_id),
                "objective_code": contract.task.objective.code,
                "title": contract.title,
                "spec_type": contract.spec_type,
                "status": milestone_status,
                "contract_status": contract.status,
                "approved_drafts": approved_drafts,
                "success_metrics": contract.success_metrics,
                "deliverables": contract.deliverables,
                "open_questions": contract.open_questions,
                "no_external_write": contract.no_external_write,
            }
        )
        for question in _list_field(contract.open_questions):
            text = str(question).strip()
            if text:
                open_questions.append(
                    {
                        "contract_id": str(contract.id),
                        "title": contract.title,
                        "question": text,
                    }
                )

    return {
        "project": project,
        "milestones": milestones,
        "open_questions": open_questions,
        "external_write_enabled": False,
    }


def serialize_product_project_roadmap(roadmap: dict) -> dict:
    project = roadmap["project"]
    return {
        "project": {
            "id": str(project.id),
            "name": project.name,
            "status": project.status,
            "repository_reference": project.repository_reference,
            "data_classification": project.data_classification,
        },
        "milestones": roadmap["milestones"],
        "open_questions": roadmap["open_questions"],
        "external_write_enabled": roadmap["external_write_enabled"],
    }


def product_feature_prioritization(*, project_id: str = "") -> dict:
    contracts = ProductSpecContract.objects.select_related("project", "task__objective").order_by("created_at")
    if project_id:
        contracts = contracts.filter(project_id=project_id)

    features = []
    for contract in contracts:
        requirements = _list_field(contract.requirements)
        for index, requirement in enumerate(requirements):
            if isinstance(requirement, dict):
                feature_id = str(requirement.get("id", f"REQ-{index + 1}")).strip() or f"REQ-{index + 1}"
                text = str(requirement.get("text", "")).strip()
                impact = int(requirement.get("impact", 3) or 3)
                urgency = int(requirement.get("urgency", 3) or 3)
                strategic_fit = int(requirement.get("strategic_fit", 3) or 3)
                confidence = int(requirement.get("confidence", 3) or 3)
                effort = int(requirement.get("effort", 3) or 3)
                risk = int(requirement.get("risk", 3) or 3)
            else:
                feature_id = f"REQ-{index + 1}"
                text = str(requirement).strip()
                impact = urgency = strategic_fit = confidence = effort = risk = 3
            if not text:
                continue
            scores = {
                "impact": max(1, min(5, impact)),
                "urgency": max(1, min(5, urgency)),
                "strategic_fit": max(1, min(5, strategic_fit)),
                "confidence": max(1, min(5, confidence)),
                "effort": max(1, min(5, effort)),
                "risk": max(1, min(5, risk)),
            }
            priority_score = (
                scores["impact"]
                * scores["urgency"]
                * scores["strategic_fit"]
                * scores["confidence"]
            ) / (scores["effort"] * scores["risk"])
            features.append(
                {
                    "project_id": str(contract.project_id),
                    "project_name": contract.project.name,
                    "contract_id": str(contract.id),
                    "objective_id": str(contract.task.objective_id),
                    "objective_code": contract.task.objective.code,
                    "feature_id": feature_id,
                    "title": text,
                    "spec_type": contract.spec_type,
                    "contract_status": contract.status,
                    "scores": scores,
                    "priority_score": round(priority_score, 2),
                    "open_question_count": len(_list_field(contract.open_questions)),
                    "no_external_write": contract.no_external_write,
                }
            )

    features.sort(key=lambda item: item["priority_score"], reverse=True)
    return {
        "features": features,
        "formula": "(impact * urgency * strategic_fit * confidence) / (effort * risk)",
        "external_write_enabled": False,
    }


def create_product_spec_contract(payload: dict, *, actor_id: str, correlation_id: str) -> ProductSpecContract:
    task_id = str(payload.get("task_id", "")).strip()
    project_id = str(payload.get("project_id", "")).strip()
    project_connection_id = payload.get("project_connection_id")
    title = str(payload.get("title", "")).strip()
    spec_type = str(payload.get("spec_type", ProductSpecContract.SpecType.PRD)).strip()
    objective = str(payload.get("objective", "")).strip()
    target_users = payload.get("target_users", [])
    problem_statement = str(payload.get("problem_statement", "")).strip()
    success_metrics = payload.get("success_metrics", [])
    requirements = payload.get("requirements", [])
    constraints = payload.get("constraints", {})
    open_questions = payload.get("open_questions", [])
    deliverables = payload.get("deliverables", [])

    if not task_id or not project_id or not title or not objective or not problem_statement:
        raise InvalidProductContractPayloadError("task_id, project_id, title, objective and problem_statement are required.")
    if spec_type not in ProductSpecContract.SpecType.values:
        raise InvalidProductContractPayloadError("spec_type must be PRD, USER_STORY, ROADMAP, RELEASE_SCOPE or DISCOVERY_BRIEF.")
    if not isinstance(target_users, list):
        raise InvalidProductContractPayloadError("target_users must be a list.")
    if not isinstance(success_metrics, list):
        raise InvalidProductContractPayloadError("success_metrics must be a list.")
    if not isinstance(requirements, list):
        raise InvalidProductContractPayloadError("requirements must be a list.")
    if not isinstance(constraints, dict):
        raise InvalidProductContractPayloadError("constraints must be an object.")
    if not isinstance(open_questions, list):
        raise InvalidProductContractPayloadError("open_questions must be a list.")
    if not isinstance(deliverables, list):
        raise InvalidProductContractPayloadError("deliverables must be a list.")

    actor = actor_id.strip() or "api"
    with transaction.atomic():
        task = Task.objects.select_for_update().get(id=task_id)
        project = Project.objects.select_for_update().get(id=project_id)
        if task.status not in {Task.Status.APPROVED, Task.Status.ASSIGNED, Task.Status.IN_PROGRESS}:
            raise ProductContractBlockedError("Product spec contracts require an approved or active Sharons task.")

        connections = ProjectConnection.objects.select_for_update().filter(
            project=project,
            active=True,
            permission_mode=ProjectConnection.PermissionMode.READ_ONLY,
        )
        if project_connection_id:
            connection = connections.get(id=int(project_connection_id))
        else:
            connection = connections.filter(adapter_type__in=["product_read_only", "product_manager_read_only"]).first()
            if connection is None:
                connection = connections.first()
        if connection is None:
            raise ProductContractBlockedError("A read-only active project connection is required.")

        contract = ProductSpecContract.objects.create(
            task=task,
            project=project,
            project_connection=connection,
            title=title,
            spec_type=spec_type,
            objective=objective,
            target_users=target_users,
            problem_statement=problem_statement,
            success_metrics=success_metrics,
            requirements=requirements,
            constraints=constraints,
            open_questions=open_questions,
            deliverables=deliverables,
            status=ProductSpecContract.Status.READY,
            no_external_write=True,
            created_by=actor,
        )
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="product.spec_contract.created",
            object_type="product.ProductSpecContract",
            object_id=str(contract.id),
            correlation_id=correlation_id,
            metadata={
                "task_id": str(task.id),
                "project_id": str(project.id),
                "project_connection_id": connection.id,
                "spec_type": contract.spec_type,
                "no_external_write": True,
            },
        )
    return contract


def _default_draft_content(contract: ProductSpecContract) -> dict:
    return {
        "spec_type": contract.spec_type,
        "objective": contract.objective,
        "problem_statement": contract.problem_statement,
        "target_users": contract.target_users,
        "success_metrics": contract.success_metrics,
        "requirements": contract.requirements,
        "constraints": contract.constraints,
        "open_questions": contract.open_questions,
        "deliverables": contract.deliverables,
        "acceptance_focus": [
            "Each requirement is traceable to the stated problem.",
            "Success metrics are measurable before release.",
            "Open questions are resolved or explicitly deferred before implementation.",
        ],
    }


def create_product_spec_draft(
    payload: dict,
    *,
    contract_id: str,
    actor_id: str,
    correlation_id: str,
) -> ProductSpecDraft:
    title = str(payload.get("title", "")).strip()
    content_override = payload.get("content")
    assumptions = payload.get("assumptions", [])
    risks = payload.get("risks", [])

    if content_override is not None and not isinstance(content_override, dict):
        raise InvalidProductContractPayloadError("content must be an object when provided.")
    if not isinstance(assumptions, list):
        raise InvalidProductContractPayloadError("assumptions must be a list.")
    if not isinstance(risks, list):
        raise InvalidProductContractPayloadError("risks must be a list.")

    actor = actor_id.strip() or "api"
    with transaction.atomic():
        contract = ProductSpecContract.objects.select_for_update().select_related("task", "project", "project_connection").get(id=contract_id)
        if contract.status not in {ProductSpecContract.Status.READY, ProductSpecContract.Status.IN_PROGRESS}:
            raise ProductContractBlockedError("Product spec drafts require a ready or in-progress product contract.")
        if contract.project_connection.permission_mode != ProjectConnection.PermissionMode.READ_ONLY:
            raise ProductContractBlockedError("Product spec drafts require a read-only project connection.")

        draft = ProductSpecDraft.objects.create(
            contract=contract,
            title=title or f"{contract.title} Draft",
            content=content_override or _default_draft_content(contract),
            assumptions=assumptions,
            risks=risks,
            review_status=ProductSpecDraft.ReviewStatus.NEEDS_REVIEW,
            no_external_write=True,
            created_by=actor,
        )
        if contract.status == ProductSpecContract.Status.READY:
            contract.status = ProductSpecContract.Status.IN_PROGRESS
            contract.save(update_fields=["status"])
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="product.spec_draft.created",
            object_type="product.ProductSpecDraft",
            object_id=str(draft.id),
            correlation_id=correlation_id,
            metadata={
                "contract_id": str(contract.id),
                "project_id": str(contract.project_id),
                "spec_type": contract.spec_type,
                "review_status": draft.review_status,
                "no_external_write": True,
            },
        )
    return draft


def review_product_spec_draft(
    payload: dict,
    *,
    draft_id: str,
    actor_id: str,
    correlation_id: str,
) -> ProductSpecDraft:
    decision = str(payload.get("decision", "")).strip()
    reviewer_notes = str(payload.get("reviewer_notes", "")).strip()
    if decision not in {ProductSpecDraft.ReviewStatus.APPROVED, ProductSpecDraft.ReviewStatus.REJECTED}:
        raise InvalidProductContractPayloadError("decision must be APPROVED or REJECTED.")

    actor = actor_id.strip() or "api"
    with transaction.atomic():
        draft = ProductSpecDraft.objects.select_for_update().select_related("contract").get(id=draft_id)
        if draft.review_status != ProductSpecDraft.ReviewStatus.NEEDS_REVIEW:
            raise ProductContractBlockedError("Only drafts that need review can be reviewed.")

        draft.review_status = decision
        content = dict(draft.content)
        content["review"] = {
            "decision": decision,
            "reviewer_notes": reviewer_notes,
            "reviewed_by": actor,
        }
        draft.content = content
        draft.save(update_fields=["review_status", "content"])

        contract = draft.contract
        if decision == ProductSpecDraft.ReviewStatus.APPROVED:
            contract.status = ProductSpecContract.Status.COMPLETED
            contract.save(update_fields=["status"])
        elif contract.status == ProductSpecContract.Status.READY:
            contract.status = ProductSpecContract.Status.IN_PROGRESS
            contract.save(update_fields=["status"])

        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="product.spec_draft.reviewed",
            object_type="product.ProductSpecDraft",
            object_id=str(draft.id),
            correlation_id=correlation_id,
            metadata={
                "contract_id": str(contract.id),
                "project_id": str(contract.project_id),
                "decision": decision,
                "contract_status": contract.status,
                "no_external_write": True,
            },
        )
    return draft


def _requirement_to_task_payload(draft: ProductSpecDraft, requirement: dict, index: int) -> dict:
    contract = draft.contract
    req_id = str(requirement.get("id", f"REQ-{index + 1}")).strip() if isinstance(requirement, dict) else f"REQ-{index + 1}"
    req_text = str(requirement.get("text", requirement)).strip() if isinstance(requirement, dict) else str(requirement).strip()
    if not req_text:
        raise InvalidProductContractPayloadError("Requirement text cannot be empty.")
    acceptance_focus = _list_field(draft.content.get("acceptance_focus", []))
    criteria = [
        {
            "description": f"Implementation satisfies product requirement {req_id}: {req_text}",
            "criterion_type": AcceptanceCriterion.CriterionType.MANUAL,
            "required": True,
        },
        {
            "description": "Evidence is attached showing the implementation was reviewed against the approved product spec.",
            "criterion_type": AcceptanceCriterion.CriterionType.EVIDENCE,
            "required": True,
        },
    ]
    for focus in acceptance_focus[:2]:
        text = str(focus).strip()
        if text:
            criteria.append(
                {
                    "description": text,
                    "criterion_type": AcceptanceCriterion.CriterionType.MANUAL,
                    "required": True,
                }
            )
    return {
        "objective_id": str(contract.task.objective_id),
        "external_key": f"product-spec:{draft.id}:{req_id}",
        "title": f"Implement {contract.title}: {req_id}",
        "business_outcome": f"{contract.project.name} advances approved product requirement {req_id}.",
        "acceptance_criteria": criteria,
    }


def propose_tasks_from_product_spec_draft(payload: dict, *, draft_id: str, actor_id: str, correlation_id: str) -> list[Task]:
    requested_limit = int(payload.get("limit", 5))
    if requested_limit < 1 or requested_limit > 10:
        raise InvalidProductContractPayloadError("limit must be between 1 and 10.")

    actor = actor_id.strip() or "api"
    with transaction.atomic():
        draft = ProductSpecDraft.objects.select_for_update().select_related("contract__task__objective", "contract__project").get(id=draft_id)
        if draft.review_status != ProductSpecDraft.ReviewStatus.APPROVED:
            raise ProductContractBlockedError("Only approved product spec drafts can propose implementation tasks.")
        if not draft.no_external_write or not draft.contract.no_external_write:
            raise ProductContractBlockedError("Product task proposal requires internal-only product artifacts.")

        requirements = _list_field(draft.content.get("requirements")) or _list_field(draft.contract.requirements)
        if not requirements:
            raise ProductContractBlockedError("Approved product spec draft has no requirements to convert into tasks.")

        tasks = []
        for index, requirement in enumerate(requirements[:requested_limit]):
            task, _created = upsert_task(
                _requirement_to_task_payload(draft, requirement, index),
                actor_id=actor,
                correlation_id=correlation_id,
            )
            tasks.append(task)

        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="product.spec_draft.tasks_proposed",
            object_type="product.ProductSpecDraft",
            object_id=str(draft.id),
            correlation_id=correlation_id,
            metadata={
                "contract_id": str(draft.contract_id),
                "project_id": str(draft.contract.project_id),
                "task_count": len(tasks),
                "no_external_write": True,
            },
        )
    return tasks
