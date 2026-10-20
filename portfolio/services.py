from django.db import transaction

from governance.models import AuditEvent
from portfolio.models import Objective, ObjectiveProjectLink, Project, ProjectConnection, ProjectStateAssessment, StrategyVersion


class ProjectRegistryError(Exception):
    code = "PROJECT_REGISTRY_ERROR"


class InvalidProjectPayloadError(ProjectRegistryError):
    code = "INVALID_PROJECT_PAYLOAD"


class InvalidProjectConnectionPayloadError(ProjectRegistryError):
    code = "INVALID_PROJECT_CONNECTION_PAYLOAD"


def serialize_project(project: Project) -> dict:
    return {
        "id": str(project.id),
        "slug": project.slug,
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "repository_provider": project.repository_provider,
        "repository_reference": project.repository_reference,
        "default_branch": project.default_branch,
        "owner": project.owner,
        "data_classification": project.data_classification,
        "metadata": project.metadata,
    }


def serialize_connection(connection: ProjectConnection) -> dict:
    return {
        "id": connection.id,
        "project_id": str(connection.project_id),
        "connection_type": connection.connection_type,
        "adapter_type": connection.adapter_type,
        "capabilities": connection.capabilities,
        "permission_mode": connection.permission_mode,
        "credential_reference": connection.credential_reference,
        "contract_version": connection.contract_version,
        "active": connection.active,
    }


def serialize_objective_project_link(link: ObjectiveProjectLink) -> dict:
    return {
        "id": link.id,
        "objective_id": str(link.objective_id),
        "objective_code": link.objective.code,
        "project_id": str(link.project_id),
        "project_slug": link.project.slug,
        "role": link.role,
        "rationale": link.rationale,
        "active": link.active,
    }


def serialize_project_state_assessment(assessment: ProjectStateAssessment) -> dict:
    return {
        "id": assessment.id,
        "project_id": str(assessment.project_id),
        "project_slug": assessment.project.slug,
        "objective_id": str(assessment.objective_id) if assessment.objective_id else None,
        "objective_code": assessment.objective.code if assessment.objective_id else None,
        "summary": assessment.summary,
        "known_assets": assessment.known_assets,
        "gaps": assessment.gaps,
        "recommended_next_steps": assessment.recommended_next_steps,
        "evidence": assessment.evidence,
        "status": assessment.status,
        "created_by": assessment.created_by,
        "created_at": assessment.created_at.isoformat(),
    }


def serialize_objective(objective: Objective) -> dict:
    return {
        "id": str(objective.id),
        "code": objective.code,
        "strategy_version": objective.strategy_version.version,
        "name": objective.name,
        "business_outcome": objective.business_outcome,
        "due_at": objective.due_at.isoformat() if objective.due_at else None,
        "status": objective.status,
        "owner_agent_id": objective.owner_agent_id,
        "weight": objective.weight,
    }


APPROVED_OBJECTIVES = [
    {
        "code": "O1",
        "name": "Mental Trainer commercial readiness",
        "business_outcome": "Complete sale-ready package with working desktop/mobile journey, pricing, landing page, billing path, and external beta validation.",
        "owner_agent_id": "chief_of_staff",
        "weight": 5,
    },
    {
        "code": "O2",
        "name": "Financial single source of truth",
        "business_outcome": "Create a unified PostgreSQL-backed view of income, expenses, and cash flow that supports pricing or investment decisions within five minutes.",
        "owner_agent_id": "finance_agent",
        "weight": 4,
    },
    {
        "code": "O3",
        "name": "Zero-touch administration",
        "business_outcome": "Reduce coordination, filing, receipts, and calendar management load with a weekly 30-minute CEO review.",
        "owner_agent_id": "administrative_agent",
        "weight": 4,
    },
    {
        "code": "O4",
        "name": "Deterministic Rules Engine with human approval",
        "business_outcome": "Translate management knowledge into validated JSON rules and approval workflows for at least two core processes.",
        "owner_agent_id": "chief_of_staff",
        "weight": 5,
    },
]


KNOWN_90_DAY_PROJECTS = [
    {
        "slug": "mental-skills-playground",
        "name": "Mental Skills Playground / Mental Trainer",
        "objective_code": "O1",
        "role": ObjectiveProjectLink.Role.PRIMARY,
        "repository_reference": "C:\\workspace\\mental-skills-playground",
        "description": "Existing Mental Trainer product work for commercial readiness.",
        "known_assets": ["README.md", "CUSTOM_GPT_INSTRUCTIONS.md", "openapi.actions.yaml", "tests"],
        "gaps": ["Confirm desktop/mobile journey", "Confirm pricing and billing path", "External beta validation still needs evidence"],
        "recommended_next_steps": ["Run product readiness assessment", "Create PM spec for sale-ready beta path"],
    },
    {
        "slug": "economic-manager",
        "name": "Economic Manager",
        "objective_code": "O2",
        "role": ObjectiveProjectLink.Role.PRIMARY,
        "repository_reference": "C:\\workspace\\economic_manager",
        "description": "Existing financial source-of-truth and reporting project.",
        "known_assets": ["README.md", "financial item import", "reports"],
        "gaps": ["Verify PostgreSQL-backed canonical data path", "Connect mail-derived financial items", "Define five-minute decision dashboard"],
        "recommended_next_steps": ["Assess current financial ingestion chain", "Create data freshness and reconciliation tasks"],
    },
    {
        "slug": "mail-manager",
        "name": "Mail Manager",
        "objective_code": "O2",
        "role": ObjectiveProjectLink.Role.DATA_SOURCE,
        "repository_reference": "C:\\workspace\\mail_manager",
        "description": "Existing Gmail ingestion and financial item extraction support project.",
        "known_assets": ["README.md", "financial item extraction", "vendor templates"],
        "gaps": ["Confirm export contract into economic_manager", "Confirm no external sending/deleting behavior"],
        "recommended_next_steps": ["Register read-only data connector", "Assess financial item schema compatibility"],
    },
    {
        "slug": "administrative-agent",
        "name": "Administrative Agent",
        "objective_code": "O3",
        "role": ObjectiveProjectLink.Role.PRIMARY,
        "repository_reference": "C:\\workspace\\administrative_agent",
        "description": "Existing administrative life-management agent project.",
        "known_assets": ["README.md", "case opening API", "documents/obligations model"],
        "gaps": ["Connect to weekly CEO review", "Define first admin domains", "Add safe prepared-communication workflow"],
        "recommended_next_steps": ["Assess active APIs and DB status", "Create zero-touch admin milestone tasks"],
    },
    {
        "slug": "task-commander",
        "name": "TaskCommander",
        "objective_code": "O3",
        "role": ObjectiveProjectLink.Role.SUPPORTING,
        "repository_reference": "C:\\workspace\\TaskCommander",
        "description": "Existing task/reminder/calendar support project.",
        "known_assets": ["calendar sync docs", "task reminder package"],
        "gaps": ["Confirm calendar-only dry-run path", "Define handoff to Executive Assistant weekly review"],
        "recommended_next_steps": ["Assess reminder/calendar integration state", "Create safe scheduling boundary tasks"],
    },
    {
        "slug": "rules-engine",
        "name": "Rules Engine",
        "objective_code": "O4",
        "role": ObjectiveProjectLink.Role.PRIMARY,
        "repository_reference": "C:\\workspace\\rules_engine",
        "description": "Existing deterministic rules engine project.",
        "known_assets": ["README.md", "shared entrypoint", "deterministic rule evaluation"],
        "gaps": ["Pick two first core processes", "Connect approval workflow", "Add validation/test fixtures for active rules"],
        "recommended_next_steps": ["Assess DSL and schema status", "Create rules process-1 and process-2 milestone tasks"],
    },
    {
        "slug": "compass",
        "name": "Compass",
        "objective_code": "O4",
        "role": ObjectiveProjectLink.Role.SUPPORTING,
        "repository_reference": "C:\\workspace\\compass",
        "description": "Existing orchestration hub with rules adapter and related project links.",
        "known_assets": ["README.md", "CURRENT_STATE.md", "rules engine adapter"],
        "gaps": ["Clarify boundary between Compass and Sharons", "Register read-only adapter contract"],
        "recommended_next_steps": ["Assess current adapter behavior", "Document integration boundary"],
    },
]


def seed_approved_objectives(*, actor_id: str, correlation_id: str) -> tuple[StrategyVersion, list[Objective]]:
    with transaction.atomic():
        strategy, _created = StrategyVersion.objects.update_or_create(
            version=1,
            defaults={
                "title": "Approved 90-day strategy",
                "content": {"horizon_days": 90, "source": "docs/chief_of_staff/SPEC_HE.md"},
                "status": StrategyVersion.Status.ACTIVE,
                "approved_by": "CEO",
            },
        )
        objectives = []
        for objective_payload in APPROVED_OBJECTIVES:
            objective, _created = Objective.objects.update_or_create(
                code=objective_payload["code"],
                defaults={
                    "strategy_version": strategy,
                    "name": objective_payload["name"],
                    "business_outcome": objective_payload["business_outcome"],
                    "status": Objective.Status.ACTIVE,
                    "owner_agent_id": objective_payload["owner_agent_id"],
                    "weight": objective_payload["weight"],
                },
            )
            objectives.append(objective)

        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor_id.strip() or "system",
            action="portfolio.objectives.seeded",
            object_type="portfolio.StrategyVersion",
            object_id=str(strategy.id),
            correlation_id=correlation_id,
            metadata={"strategy_version": strategy.version, "objective_codes": [item["code"] for item in APPROVED_OBJECTIVES]},
        )
    return strategy, objectives


def create_project(payload: dict, *, actor_id: str, correlation_id: str) -> Project:
    slug = str(payload.get("slug", "")).strip()
    name = str(payload.get("name", "")).strip()
    owner = str(payload.get("owner", "")).strip()
    if not slug or not name or not owner:
        raise InvalidProjectPayloadError("slug, name, and owner are required.")

    status = str(payload.get("status", Project.Status.IDEA)).strip() or Project.Status.IDEA
    if status not in Project.Status.values:
        raise InvalidProjectPayloadError("status must be a valid project status.")

    data_classification = str(payload.get("data_classification", Project.DataClassification.INTERNAL)).strip()
    if data_classification not in Project.DataClassification.values:
        raise InvalidProjectPayloadError("data_classification must be valid.")

    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise InvalidProjectPayloadError("metadata must be an object.")

    with transaction.atomic():
        project = Project.objects.create(
            slug=slug,
            name=name,
            description=str(payload.get("description", "")).strip(),
            status=status,
            repository_provider=str(payload.get("repository_provider", "")).strip(),
            repository_reference=str(payload.get("repository_reference", "")).strip(),
            default_branch=str(payload.get("default_branch", "")).strip(),
            owner=owner,
            data_classification=data_classification,
            metadata=metadata,
        )
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor_id.strip() or "api",
            action="portfolio.project.created",
            object_type="portfolio.Project",
            object_id=str(project.id),
            correlation_id=correlation_id,
            metadata={"slug": project.slug, "status": project.status},
        )
    return project


def register_known_90_day_projects(*, actor_id: str, correlation_id: str) -> dict:
    actor = actor_id.strip() or "api"
    seed_approved_objectives(actor_id=actor, correlation_id=correlation_id)
    registered_projects = []
    links = []
    assessments = []
    with transaction.atomic():
        for item in KNOWN_90_DAY_PROJECTS:
            objective = Objective.objects.select_for_update().get(code=item["objective_code"], status=Objective.Status.ACTIVE)
            project, _created = Project.objects.update_or_create(
                slug=item["slug"],
                defaults={
                    "name": item["name"],
                    "description": item["description"],
                    "status": Project.Status.ACTIVE,
                    "repository_provider": "local",
                    "repository_reference": item["repository_reference"],
                    "default_branch": "",
                    "owner": objective.owner_agent_id or "chief_of_staff",
                    "data_classification": Project.DataClassification.INTERNAL,
                    "metadata": {
                        "source": "known_90_day_project_registry",
                        "objective_code": objective.code,
                        "partly_developed": True,
                    },
                },
            )
            connection, _connection_created = ProjectConnection.objects.get_or_create(
                project=project,
                connection_type=ProjectConnection.ConnectionType.REPOSITORY,
                adapter_type="local_repository_read_only",
                defaults={
                    "capabilities": {"status": True, "assessment": True, "write": False},
                    "permission_mode": ProjectConnection.PermissionMode.READ_ONLY,
                    "active": True,
                },
            )
            link, _link_created = ObjectiveProjectLink.objects.update_or_create(
                objective=objective,
                project=project,
                defaults={"role": item["role"], "rationale": item["description"], "active": True},
            )
            ProjectStateAssessment.objects.filter(project=project, objective=objective, status=ProjectStateAssessment.Status.CURRENT).update(
                status=ProjectStateAssessment.Status.SUPERSEDED
            )
            assessment = ProjectStateAssessment.objects.create(
                project=project,
                objective=objective,
                summary=f"{project.name} is an existing partly developed project linked to {objective.code}; work should start from current-state assessment, not from scratch.",
                known_assets=item["known_assets"],
                gaps=item["gaps"],
                recommended_next_steps=item["recommended_next_steps"],
                evidence=[{"type": "workspace_path", "reference": item["repository_reference"]}],
                status=ProjectStateAssessment.Status.CURRENT,
                created_by=actor,
            )
            registered_projects.append(project)
            links.append(link)
            assessments.append(assessment)

        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="portfolio.known_90_day_projects.registered",
            object_type="portfolio.Project",
            object_id="known_90_day_projects",
            correlation_id=correlation_id,
            metadata={
                "project_slugs": [project.slug for project in registered_projects],
                "count": len(registered_projects),
                "no_external_action": True,
            },
        )
    return {"projects": registered_projects, "links": links, "assessments": assessments}


def create_project_connection(project: Project, payload: dict, *, actor_id: str, correlation_id: str) -> ProjectConnection:
    connection_type = str(payload.get("connection_type", "")).strip()
    adapter_type = str(payload.get("adapter_type", "")).strip()
    if connection_type not in ProjectConnection.ConnectionType.values or not adapter_type:
        raise InvalidProjectConnectionPayloadError("connection_type and adapter_type are required.")

    permission_mode = str(payload.get("permission_mode", ProjectConnection.PermissionMode.READ_ONLY)).strip()
    if permission_mode not in ProjectConnection.PermissionMode.values:
        raise InvalidProjectConnectionPayloadError("permission_mode must be valid.")

    capabilities = payload.get("capabilities", {})
    if not isinstance(capabilities, dict):
        raise InvalidProjectConnectionPayloadError("capabilities must be an object.")

    with transaction.atomic():
        connection = ProjectConnection.objects.create(
            project=project,
            connection_type=connection_type,
            adapter_type=adapter_type,
            capabilities=capabilities,
            permission_mode=permission_mode,
            credential_reference=str(payload.get("credential_reference", "")).strip(),
            contract_version=int(payload.get("contract_version", 1)),
            active=bool(payload.get("active", True)),
        )
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor_id.strip() or "api",
            action="portfolio.project_connection.created",
            object_type="portfolio.ProjectConnection",
            object_id=str(connection.id),
            correlation_id=correlation_id,
            metadata={
                "project_id": str(project.id),
                "connection_type": connection.connection_type,
                "permission_mode": connection.permission_mode,
            },
        )
    return connection
