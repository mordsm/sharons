import hashlib
import json

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.models import IdempotencyRecord, MemoryRecord
from developer.models import DeveloperWorkContract, ImplementationPlan
from developer.services import create_implementation_plan
from executive_assistant.models import ExecutiveBrief, ExecutiveBriefTaskProposal, ExecutiveEmailDraft
from finance.models import FinancialRecord
from governance.models import ApprovalRequest, AuditEvent, RuleEngineWorkItem
from operations.models import AcceptanceCriterion, AgentDefinition, Task
from operations.services import upsert_task
from portfolio.models import Objective
from product.models import ProductSpecContract, ProductSpecDraft
from product.services import create_product_spec_draft
from project_manager.models import BlockerReview, ExecutionReview, MilestoneProposal
from qa.models import VerificationReview


class IntakeError(Exception):
    code = "INTAKE_ERROR"
    status_code = 400


class MissingHeaderError(IntakeError):
    code = "MISSING_REQUIRED_HEADER"


class InvalidPayloadError(IntakeError):
    code = "INVALID_PAYLOAD"


class ObjectiveNotFoundError(IntakeError):
    code = "OBJECTIVE_NOT_FOUND"
    status_code = 404


class CosPlanningError(Exception):
    code = "COS_PLANNING_ERROR"
    status_code = 400


class InvalidCosPlanningPayloadError(CosPlanningError):
    code = "INVALID_COS_PLANNING_PAYLOAD"


class CosObjectiveNotFoundError(CosPlanningError):
    code = "OBJECTIVE_NOT_FOUND"
    status_code = 404


class IdempotencyConflictError(IntakeError):
    code = "IDEMPOTENCY_CONFLICT"
    status_code = 409


class MemoryError(Exception):
    code = "MEMORY_ERROR"
    status_code = 400


class InvalidMemoryPayloadError(MemoryError):
    code = "INVALID_MEMORY_PAYLOAD"


class EventRecordError(Exception):
    code = "EVENT_RECORD_ERROR"
    status_code = 400


class InvalidEventPayloadError(EventRecordError):
    code = "INVALID_EVENT_PAYLOAD"


class ConversationFinalizeError(Exception):
    code = "CONVERSATION_FINALIZE_ERROR"
    status_code = 400


class InvalidConversationPayloadError(ConversationFinalizeError):
    code = "INVALID_CONVERSATION_PAYLOAD"


class CockpitActionError(Exception):
    code = "COCKPIT_ACTION_ERROR"


class CockpitActionUnavailableError(CockpitActionError):
    code = "COCKPIT_ACTION_UNAVAILABLE"


def canonical_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def serialize_memory_record(record: MemoryRecord) -> dict:
    return {
        "id": str(record.id),
        "record_type": record.record_type,
        "title": record.title,
        "content": record.content,
        "source_type": record.source_type,
        "source_id": record.source_id,
        "owner": record.owner,
        "classification": record.classification,
        "verification_status": record.verification_status,
        "version": record.version,
        "valid_from": record.valid_from.isoformat() if record.valid_from else None,
        "valid_until": record.valid_until.isoformat() if record.valid_until else None,
        "supersedes_id": str(record.supersedes_id) if record.supersedes_id else None,
        "embedding_reference": record.embedding_reference,
        "created_at": record.created_at.isoformat(),
    }


def create_memory_record(payload: dict, *, actor_id: str, correlation_id: str) -> MemoryRecord:
    record_type = str(payload.get("record_type", "")).strip()
    title = str(payload.get("title", "")).strip()
    content = payload.get("content", {})
    source_type = str(payload.get("source_type", "")).strip()
    source_id = str(payload.get("source_id", "")).strip()
    owner = str(payload.get("owner", actor_id)).strip()
    classification = str(payload.get("classification", MemoryRecord.Classification.INTERNAL)).strip()
    verification_status = str(payload.get("verification_status", MemoryRecord.VerificationStatus.UNVERIFIED)).strip()
    supersedes_id = str(payload.get("supersedes_id", "")).strip()

    if record_type not in MemoryRecord.RecordType.values:
        raise InvalidMemoryPayloadError("record_type is required and must be valid.")
    if source_type not in MemoryRecord.SourceType.values:
        raise InvalidMemoryPayloadError("source_type is required and must be valid.")
    if classification not in MemoryRecord.Classification.values:
        raise InvalidMemoryPayloadError("classification must be valid.")
    if verification_status not in MemoryRecord.VerificationStatus.values:
        raise InvalidMemoryPayloadError("verification_status must be valid.")
    if not title or not source_id or not owner:
        raise InvalidMemoryPayloadError("title, source_id and owner are required.")
    if not isinstance(content, dict):
        raise InvalidMemoryPayloadError("content must be an object.")
    if payload.get("embedding_reference"):
        raise InvalidMemoryPayloadError("embedding_reference is not supported in the initial memory slice.")
    if (
        source_type == MemoryRecord.SourceType.CONVERSATION
        and record_type == MemoryRecord.RecordType.DECISION
        and verification_status == MemoryRecord.VerificationStatus.VERIFIED
    ):
        raise InvalidMemoryPayloadError("Conversation summaries cannot become verified decisions automatically.")

    with transaction.atomic():
        supersedes = None
        if supersedes_id:
            supersedes = MemoryRecord.objects.select_for_update().get(id=supersedes_id)
        record = MemoryRecord.objects.create(
            record_type=record_type,
            title=title,
            content=content,
            source_type=source_type,
            source_id=source_id,
            owner=owner,
            classification=classification,
            verification_status=verification_status,
            version=int(payload.get("version", 1)),
            supersedes=supersedes,
        )
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor_id.strip() or "api",
            action="core.memory.created",
            object_type="core.MemoryRecord",
            object_id=str(record.id),
            correlation_id=correlation_id,
            metadata={
                "record_type": record.record_type,
                "source_type": record.source_type,
                "source_id": record.source_id,
                "classification": record.classification,
                "verification_status": record.verification_status,
            },
        )
    return record


def record_internal_event(payload: dict, *, actor_id: str, correlation_id: str) -> AuditEvent:
    action = str(payload.get("action", "")).strip()
    object_type = str(payload.get("object_type", "")).strip()
    object_id = str(payload.get("object_id", "")).strip()
    metadata = payload.get("metadata", {})
    if not action or not object_type or not object_id:
        raise InvalidEventPayloadError("action, object_type and object_id are required.")
    if not isinstance(metadata, dict):
        raise InvalidEventPayloadError("metadata must be an object.")
    with transaction.atomic():
        event = AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor_id.strip() or "api",
            action=action,
            object_type=object_type,
            object_id=object_id,
            correlation_id=correlation_id,
            metadata=metadata,
        )
    return event


def finalize_conversation(payload: dict, *, actor_id: str, correlation_id: str) -> MemoryRecord:
    conversation_id = str(payload.get("conversation_id", "")).strip()
    title = str(payload.get("title", "")).strip()
    summary = str(payload.get("summary", "")).strip()
    decisions = payload.get("decisions", [])
    action_items = payload.get("action_items", [])
    if not conversation_id or not title or not summary:
        raise InvalidConversationPayloadError("conversation_id, title and summary are required.")
    if not isinstance(decisions, list):
        raise InvalidConversationPayloadError("decisions must be a list.")
    if not isinstance(action_items, list):
        raise InvalidConversationPayloadError("action_items must be a list.")

    record_payload = {
        "record_type": MemoryRecord.RecordType.STATUS_SUMMARY,
        "title": title,
        "content": {
            "summary": summary,
            "decisions": decisions,
            "action_items": action_items,
            "note": "Conversation summaries are unverified memory until converted into approved decisions or tasks.",
        },
        "source_type": MemoryRecord.SourceType.CONVERSATION,
        "source_id": conversation_id,
        "owner": str(payload.get("owner", actor_id)).strip() or actor_id,
        "classification": str(payload.get("classification", MemoryRecord.Classification.INTERNAL)).strip(),
        "verification_status": MemoryRecord.VerificationStatus.UNVERIFIED,
    }
    return create_memory_record(record_payload, actor_id=actor_id, correlation_id=correlation_id)


def search_memory_records(
    *,
    q: str = "",
    record_type: str = "",
    classification: str = "",
    verification_status: str = "",
    source_type: str = "",
    limit: int = 20,
) -> list[MemoryRecord]:
    queryset = MemoryRecord.objects.order_by("-created_at")
    if q:
        queryset = queryset.filter(title__icontains=q.strip()) | MemoryRecord.objects.filter(source_id__icontains=q.strip()) | MemoryRecord.objects.filter(owner__icontains=q.strip())
        queryset = queryset.order_by("-created_at")
    if record_type:
        queryset = queryset.filter(record_type=record_type)
    if classification:
        queryset = queryset.filter(classification=classification)
    if verification_status:
        queryset = queryset.filter(verification_status=verification_status)
    if source_type:
        queryset = queryset.filter(source_type=source_type)
    return list(queryset[:limit])


def agent_queue_overview() -> list[dict]:
    open_task_statuses = [
        Task.Status.DRAFT,
        Task.Status.PLANNED,
        Task.Status.PENDING_APPROVAL,
        Task.Status.APPROVED,
        Task.Status.ASSIGNED,
        Task.Status.IN_PROGRESS,
        Task.Status.BLOCKED,
        Task.Status.DELIVERED_UNVERIFIED,
        Task.Status.VERIFYING,
    ]
    completed_rule_statuses = [RuleEngineWorkItem.Status.COMPLETED, RuleEngineWorkItem.Status.CANCELLED]
    unreconciled_finance_statuses = [
        FinancialRecord.ReconciliationStatus.UNRECONCILED,
        FinancialRecord.ReconciliationStatus.NEEDS_REVIEW,
        FinancialRecord.ReconciliationStatus.DISCREPANCY,
    ]
    agent_ids = [
        "chief_of_staff",
        "product_manager",
        "executive_assistant",
        "finance_agent",
        "developer",
        "project_manager",
        "qa",
    ]
    registrations = {
        agent.agent_id: agent
        for agent in AgentDefinition.objects.filter(agent_id__in=agent_ids)
    }
    product_ready_contracts = ProductSpecContract.objects.filter(status=ProductSpecContract.Status.READY)
    developer_ready_contracts = DeveloperWorkContract.objects.filter(status=DeveloperWorkContract.Status.READY)
    active_objectives = Objective.objects.filter(status=Objective.Status.ACTIVE)
    qa_ready_tasks = Task.objects.filter(status=Task.Status.DELIVERED_UNVERIFIED)
    finance_review_records = FinancialRecord.objects.filter(
        reconciliation_status__in=[
            FinancialRecord.ReconciliationStatus.UNRECONCILED,
            FinancialRecord.ReconciliationStatus.DISCREPANCY,
        ]
    )

    return [
        {
            "agent_id": "chief_of_staff",
            "label": "Chief of Staff",
            "registered": registrations.get("chief_of_staff").active if registrations.get("chief_of_staff") else False,
            "primary_queue": RuleEngineWorkItem.objects.filter(owner_agent_id="chief_of_staff").exclude(status__in=completed_rule_statuses).count(),
            "secondary_queue": ApprovalRequest.objects.filter(status=ApprovalRequest.Status.PENDING).count(),
            "risk_queue": Task.objects.filter(status=Task.Status.BLOCKED).count(),
            "primary_label": "Rule Work",
            "secondary_label": "Approvals",
            "risk_label": "Blocked",
            "href": "executive-dashboard",
        },
        {
            "agent_id": "product_manager",
            "label": "Product Manager",
            "registered": registrations.get("product_manager").active if registrations.get("product_manager") else False,
            "primary_queue": ProductSpecContract.objects.exclude(status__in=[ProductSpecContract.Status.COMPLETED, ProductSpecContract.Status.CANCELLED]).count(),
            "secondary_queue": ProductSpecDraft.objects.filter(review_status=ProductSpecDraft.ReviewStatus.NEEDS_REVIEW).count(),
            "risk_queue": ProductSpecContract.objects.exclude(open_questions=[]).exclude(status__in=[ProductSpecContract.Status.COMPLETED, ProductSpecContract.Status.CANCELLED]).count(),
            "primary_label": "Contracts",
            "secondary_label": "Draft Review",
            "risk_label": "Open Qs",
            "href": "product-manager-status",
            "action": "create_next_product_draft",
            "action_label": "Draft Next Spec",
            "action_enabled": product_ready_contracts.exists(),
        },
        {
            "agent_id": "executive_assistant",
            "label": "Executive Assistant",
            "registered": registrations.get("executive_assistant").active if registrations.get("executive_assistant") else False,
            "primary_queue": RuleEngineWorkItem.objects.filter(owner_agent_id="executive_assistant").exclude(status__in=completed_rule_statuses).count(),
            "secondary_queue": ExecutiveEmailDraft.objects.filter(review_status=ExecutiveEmailDraft.ReviewStatus.NEEDS_REVIEW).count(),
            "risk_queue": ExecutiveBriefTaskProposal.objects.filter(review_status=ExecutiveBriefTaskProposal.ReviewStatus.PENDING).count(),
            "primary_label": "Rule Work",
            "secondary_label": "Drafts",
            "risk_label": "Task Props",
            "href": "executive-assistant-dashboard",
            "action": "create_next_executive_brief",
            "action_label": "Create Brief",
            "action_enabled": True,
        },
        {
            "agent_id": "finance_agent",
            "label": "Finance",
            "registered": registrations.get("finance_agent").active if registrations.get("finance_agent") else False,
            "primary_queue": RuleEngineWorkItem.objects.filter(owner_agent_id="finance_agent").exclude(status__in=completed_rule_statuses).count(),
            "secondary_queue": FinancialRecord.objects.filter(reconciliation_status__in=unreconciled_finance_statuses).count(),
            "risk_queue": FinancialRecord.objects.filter(reconciliation_status=FinancialRecord.ReconciliationStatus.DISCREPANCY).count(),
            "primary_label": "Rule Work",
            "secondary_label": "Reconcile",
            "risk_label": "Disputes",
            "href": "finance-dashboard",
            "action": "open_next_finance_review",
            "action_label": "Open Review",
            "action_enabled": finance_review_records.exists(),
        },
        {
            "agent_id": "developer",
            "label": "Developer",
            "registered": registrations.get("developer").active if registrations.get("developer") else False,
            "primary_queue": DeveloperWorkContract.objects.exclude(status__in=[DeveloperWorkContract.Status.DELIVERED, DeveloperWorkContract.Status.CANCELLED]).count(),
            "secondary_queue": ImplementationPlan.objects.filter(status=ImplementationPlan.Status.NEEDS_REVIEW).count(),
            "risk_queue": ImplementationPlan.objects.filter(status=ImplementationPlan.Status.DELIVERED_UNVERIFIED).count(),
            "primary_label": "Contracts",
            "secondary_label": "Plans",
            "risk_label": "Unverified",
            "href": "developer-status",
            "action": "create_next_developer_plan",
            "action_label": "Plan Next Build",
            "action_enabled": developer_ready_contracts.exists(),
        },
        {
            "agent_id": "project_manager",
            "label": "Project Manager",
            "registered": registrations.get("project_manager").active if registrations.get("project_manager") else False,
            "primary_queue": Task.objects.filter(status__in=open_task_statuses).count(),
            "secondary_queue": MilestoneProposal.objects.count(),
            "risk_queue": BlockerReview.objects.filter(escalation_required=True).count() + Task.objects.filter(status=Task.Status.BLOCKED).count(),
            "primary_label": "Open Tasks",
            "secondary_label": "Milestones",
            "risk_label": "Escalations",
            "href": "project-manager-status",
            "action": "create_next_execution_review",
            "action_label": "Review Execution",
            "action_enabled": active_objectives.exists(),
        },
        {
            "agent_id": "qa",
            "label": "QA",
            "registered": registrations.get("qa").active if registrations.get("qa") else False,
            "primary_queue": Task.objects.filter(status=Task.Status.DELIVERED_UNVERIFIED).count(),
            "secondary_queue": VerificationReview.objects.count(),
            "risk_queue": Task.objects.filter(status=Task.Status.VERIFYING).count(),
            "primary_label": "Verify",
            "secondary_label": "Reviews",
            "risk_label": "Checking",
            "href": "qa-status",
            "action": "create_next_qa_review",
            "action_label": "Review Evidence",
            "action_enabled": qa_ready_tasks.exists(),
        },
    ]


def create_next_product_draft_from_cockpit(*, actor_id: str, correlation_id: str) -> ProductSpecDraft:
    contract = ProductSpecContract.objects.filter(status=ProductSpecContract.Status.READY).order_by("created_at").first()
    if contract is None:
        raise CockpitActionUnavailableError("No ready product spec contract is available.")
    return create_product_spec_draft(
        {
            "title": f"{contract.title} Draft",
            "assumptions": ["Generated from Executive Overview cockpit action."],
            "risks": ["Requires human review before implementation tasks are proposed."],
        },
        contract_id=str(contract.id),
        actor_id=actor_id,
        correlation_id=correlation_id,
    )


def create_next_developer_plan_from_cockpit(*, actor_id: str, correlation_id: str) -> ImplementationPlan:
    contract = DeveloperWorkContract.objects.filter(status=DeveloperWorkContract.Status.READY).order_by("created_at").first()
    if contract is None:
        raise CockpitActionUnavailableError("No ready developer work contract is available.")
    return create_implementation_plan(
        {
            "title": f"{contract.title} Implementation Plan",
            "summary": contract.objective,
            "planned_changes": contract.scope or ["Inspect the assigned project area and propose the minimal implementation changes."],
            "verification_plan": contract.acceptance_focus or ["Attach evidence that the implementation plan satisfies the assigned acceptance criteria."],
            "risks": ["Generated from Executive Overview cockpit action; requires review before delivery."],
        },
        contract_id=str(contract.id),
        actor_id=actor_id,
        correlation_id=correlation_id,
    )


def create_next_execution_review_from_cockpit(*, actor_id: str, correlation_id: str) -> ExecutionReview:
    objective = Objective.objects.filter(status=Objective.Status.ACTIVE).order_by("code").first()
    if objective is None:
        raise CockpitActionUnavailableError("No active objective is available for execution review.")

    from project_manager.services import create_execution_review

    return create_execution_review(
        {"objective_id": str(objective.id)},
        actor_id=actor_id,
        correlation_id=correlation_id,
    )


def create_next_qa_review_from_cockpit(*, actor_id: str, correlation_id: str) -> VerificationReview:
    task = Task.objects.filter(status=Task.Status.DELIVERED_UNVERIFIED).order_by("updated_at").first()
    if task is None:
        raise CockpitActionUnavailableError("No delivered-unverified task is available for QA review.")

    from qa.models import VerificationReview
    from qa.services import review_task_evidence

    return review_task_evidence(
        {
            "decision": VerificationReview.Decision.NEEDS_MORE_EVIDENCE,
            "notes": "Cockpit review opened for QA. Evidence remains unaccepted until explicit QA acceptance.",
        },
        task_id=str(task.id),
        actor_id=actor_id,
        correlation_id=correlation_id,
    )


def create_next_executive_brief_from_cockpit(*, actor_id: str, correlation_id: str):
    from executive_assistant.models import ExecutiveBrief
    from executive_assistant.services import create_executive_brief

    return create_executive_brief(
        {
            "brief_type": ExecutiveBrief.BriefType.WEEKLY_REVIEW_PREP,
            "title": "Cockpit Executive Brief",
            "source_window": {"source": "executive_dashboard"},
        },
        actor_id=actor_id,
        correlation_id=correlation_id,
    )


def open_next_finance_review_from_cockpit(*, actor_id: str, correlation_id: str) -> FinancialRecord:
    record = (
        FinancialRecord.objects.filter(
            reconciliation_status__in=[
                FinancialRecord.ReconciliationStatus.UNRECONCILED,
                FinancialRecord.ReconciliationStatus.DISCREPANCY,
            ]
        )
        .order_by("occurred_on", "created_at")
        .first()
    )
    if record is None:
        raise CockpitActionUnavailableError("No unreconciled or disputed finance record is available for review.")

    from finance.services import update_reconciliation

    return update_reconciliation(
        str(record.id),
        status=FinancialRecord.ReconciliationStatus.NEEDS_REVIEW,
        notes="Opened from Executive Overview cockpit for finance review.",
        actor_id=actor_id,
        correlation_id=correlation_id,
    )


def executive_overview() -> dict:
    active_objectives = Objective.objects.filter(status=Objective.Status.ACTIVE).order_by("code")
    tasks = Task.objects.all()
    pending_approvals = ApprovalRequest.objects.filter(status=ApprovalRequest.Status.PENDING).order_by("expires_at")
    blocked_tasks = tasks.filter(status=Task.Status.BLOCKED).order_by("-updated_at")
    unverified_tasks = tasks.filter(status=Task.Status.DELIVERED_UNVERIFIED).order_by("-updated_at")
    active_agents = AgentDefinition.objects.filter(active=True).order_by("agent_id")
    chief_rule_work_items = RuleEngineWorkItem.objects.filter(owner_agent_id="chief_of_staff").exclude(
        status__in=[RuleEngineWorkItem.Status.COMPLETED, RuleEngineWorkItem.Status.CANCELLED]
    )

    return {
        "counts": {
            "active_objectives": active_objectives.count(),
            "open_tasks": tasks.exclude(status__in=[Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.FAILED]).count(),
            "blocked_tasks": blocked_tasks.count(),
            "unverified_deliveries": unverified_tasks.count(),
            "pending_approvals": pending_approvals.count(),
            "active_agents": active_agents.count(),
            "chief_rule_engine_work_items": chief_rule_work_items.count(),
        },
        "active_objectives": list(active_objectives[:8]),
        "pending_approvals": list(pending_approvals[:8]),
        "blocked_tasks": list(blocked_tasks[:8]),
        "unverified_tasks": list(unverified_tasks[:8]),
        "chief_rule_engine_work_items": list(chief_rule_work_items.select_related("run").order_by("-created_at")[:8]),
        "active_agents": list(active_agents[:8]),
        "agent_queues": agent_queue_overview(),
        "recent_audit_events": list(AuditEvent.objects.all()[:10]),
    }


def serialize_task_summary(task: Task) -> dict:
    return {
        "id": str(task.id),
        "title": task.title,
        "status": task.status,
        "version": task.version,
        "objective_code": task.objective.code,
        "objective_name": task.objective.name,
        "owner_agent_id": task.owner_agent_id,
        "updated_at": task.updated_at.isoformat(),
    }


def _open_objective_tasks(objective: Objective):
    return objective.tasks.exclude(status__in=[Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.FAILED])


def objective_health(objective: Objective, *, now=None) -> dict:
    now = now or timezone.now()
    open_tasks = _open_objective_tasks(objective)
    blocked_tasks = open_tasks.filter(status=Task.Status.BLOCKED).order_by("-updated_at")
    unverified_tasks = open_tasks.filter(status=Task.Status.DELIVERED_UNVERIFIED).order_by("-updated_at")
    pending_tasks = open_tasks.filter(status=Task.Status.PENDING_APPROVAL).order_by("-updated_at")
    stale_cutoff = now - timezone.timedelta(days=14)
    stale_tasks = open_tasks.filter(updated_at__lt=stale_cutoff).order_by("updated_at")

    reasons: list[str] = []
    status = "ON_TRACK"
    if not open_tasks.exists():
        status = "UNKNOWN"
        reasons.append("No open tasks are registered for this objective.")
    if pending_tasks.exists():
        status = "AT_RISK"
        reasons.append("One or more tasks are waiting for approval.")
    if unverified_tasks.exists():
        status = "AT_RISK"
        reasons.append("Delivered work is waiting for verification.")
    if stale_tasks.exists():
        status = "AT_RISK"
        reasons.append("One or more open tasks have not changed in 14 days.")
    if objective.due_at and objective.due_at < now:
        status = "AT_RISK"
        reasons.append("Objective due date has passed.")
    if blocked_tasks.exists():
        status = "BLOCKED"
        reasons.append("One or more open tasks are blocked.")
    if status == "ON_TRACK":
        reasons.append("Open work exists and no blocking or risk signals were detected.")

    return {
        "objective": objective,
        "status": status,
        "reasons": reasons,
        "counts": {
            "open_tasks": open_tasks.count(),
            "blocked_tasks": blocked_tasks.count(),
            "pending_approval_tasks": pending_tasks.count(),
            "unverified_deliveries": unverified_tasks.count(),
            "stale_tasks": stale_tasks.count(),
        },
        "blocked_tasks": list(blocked_tasks[:5]),
        "unverified_tasks": list(unverified_tasks[:5]),
        "pending_approval_tasks": list(pending_tasks[:5]),
        "stale_tasks": list(stale_tasks[:5]),
    }


def serialize_objective_summary(objective: Objective) -> dict:
    return {
        "id": str(objective.id),
        "code": objective.code,
        "name": objective.name,
        "business_outcome": objective.business_outcome,
        "owner_agent_id": objective.owner_agent_id,
        "due_at": objective.due_at.isoformat() if objective.due_at else None,
        "status": objective.status,
    }


def serialize_objective_health(health: dict) -> dict:
    return {
        "objective": serialize_objective_summary(health["objective"]),
        "health_status": health["status"],
        "reasons": health["reasons"],
        "counts": health["counts"],
        "blocked_tasks": [serialize_task_summary(task) for task in health["blocked_tasks"]],
        "unverified_tasks": [serialize_task_summary(task) for task in health["unverified_tasks"]],
        "pending_approval_tasks": [serialize_task_summary(task) for task in health["pending_approval_tasks"]],
        "stale_tasks": [serialize_task_summary(task) for task in health["stale_tasks"]],
    }


def objective_operating_dashboard() -> dict:
    health_items = objective_health_report()
    status_counts = {
        "ON_TRACK": 0,
        "AT_RISK": 0,
        "BLOCKED": 0,
        "UNKNOWN": 0,
    }
    objectives = []
    critical_path = []
    stale_tasks = []
    for health in health_items:
        status_counts[health["status"]] += 1
        review = objective_operating_review(objective_id=str(health["objective"].id))
        serialized_health = serialize_objective_health(health)
        recommendations = review["recommendations"]
        objectives.append(
            {
                "objective": serialize_objective_summary(health["objective"]),
                "health": serialized_health,
                "recommendations": recommendations,
                "open_task_count": len(review["open_tasks"]),
                "pending_approval_count": len(review["pending_approvals"]),
            }
        )
        for task in health["blocked_tasks"] + health["pending_approval_tasks"] + health["unverified_tasks"]:
            critical_path.append(
                {
                    "objective": serialize_objective_summary(health["objective"]),
                    "task": serialize_task_summary(task),
                    "reason": task.status,
                }
            )
        for task in health["stale_tasks"]:
            stale_tasks.append(
                {
                    "objective": serialize_objective_summary(health["objective"]),
                    "task": serialize_task_summary(task),
                }
            )

    return {
        "generated_at": timezone.now(),
        "status_counts": status_counts,
        "objectives": objectives,
        "critical_path": critical_path[:20],
        "stale_tasks": stale_tasks[:20],
        "no_external_action": True,
    }


def serialize_objective_operating_dashboard(dashboard: dict) -> dict:
    return {
        "generated_at": dashboard["generated_at"].isoformat(),
        "status_counts": dashboard["status_counts"],
        "objectives": dashboard["objectives"],
        "critical_path": dashboard["critical_path"],
        "stale_tasks": dashboard["stale_tasks"],
        "no_external_action": dashboard["no_external_action"],
    }


def objective_health_report() -> list[dict]:
    objectives = Objective.objects.filter(status=Objective.Status.ACTIVE).order_by("code")
    return [objective_health(objective) for objective in objectives]


def objective_operating_review(*, objective_id: str) -> dict:
    try:
        objective = Objective.objects.get(id=objective_id, status=Objective.Status.ACTIVE)
    except Objective.DoesNotExist as exc:
        raise CosObjectiveNotFoundError("Active objective was not found.") from exc

    health = objective_health(objective)
    open_tasks = _open_objective_tasks(objective).order_by("-updated_at")
    completed_tasks = objective.tasks.filter(status=Task.Status.COMPLETED).order_by("-updated_at")
    pending_approvals = ApprovalRequest.objects.filter(
        subject_type="operations.Task",
        subject_id__in=[str(task.id) for task in open_tasks],
        status=ApprovalRequest.Status.PENDING,
    ).order_by("expires_at")
    recommendations = recommend_next_actions_for_objective(health)

    return {
        "objective": objective,
        "health": health,
        "open_tasks": list(open_tasks[:20]),
        "completed_tasks": list(completed_tasks[:10]),
        "pending_approvals": list(pending_approvals[:10]),
        "recommendations": recommendations,
    }


def serialize_objective_operating_review(review: dict) -> dict:
    return {
        "objective": serialize_objective_summary(review["objective"]),
        "health": serialize_objective_health(review["health"]),
        "open_tasks": [serialize_task_summary(task) for task in review["open_tasks"]],
        "completed_tasks": [serialize_task_summary(task) for task in review["completed_tasks"]],
        "pending_approvals": [serialize_approval_summary(approval) for approval in review["pending_approvals"]],
        "recommendations": review["recommendations"],
    }


def recommend_next_actions_for_objective(health: dict) -> list[dict]:
    objective = health["objective"]
    if health["counts"]["blocked_tasks"]:
        return [
            {
                "key": "resolve-blockers",
                "title": f"Resolve blockers for {objective.code}",
                "reason": "Blocked tasks are the highest-risk signal for the objective.",
                "business_outcome": f"Blocking issues for {objective.name} are resolved, reassigned or escalated.",
                "acceptance_criteria": ["Each blocked task has a documented owner, next step and unblock condition."],
            }
        ]
    if health["counts"]["unverified_deliveries"]:
        return [
            {
                "key": "verify-deliveries",
                "title": f"Verify delivered work for {objective.code}",
                "reason": "Delivered-unverified work cannot be counted as completed operating progress.",
                "business_outcome": f"Delivered work for {objective.name} is accepted, rejected or returned with evidence gaps.",
                "acceptance_criteria": ["Every delivered-unverified task is reviewed against acceptance criteria and evidence."],
            }
        ]
    if health["counts"]["pending_approval_tasks"]:
        return [
            {
                "key": "prepare-approval-review",
                "title": f"Prepare approval review for {objective.code}",
                "reason": "Pending approval work needs a CEO or delegated decision.",
                "business_outcome": f"Approval requests for {objective.name} are ready for a clear decision.",
                "acceptance_criteria": ["Each pending approval has context, options, risk and recommendation documented."],
            }
        ]
    if health["counts"]["open_tasks"] == 0:
        return [
            {
                "key": "define-next-milestone",
                "title": f"Define next milestone for {objective.code}",
                "reason": "The objective has no open work and cannot move without a next task.",
                "business_outcome": f"The next measurable milestone for {objective.name} is clear and actionable.",
                "acceptance_criteria": ["Milestone, owner, due date assumption and verification evidence are documented."],
            }
        ]
    return [
        {
            "key": "continue-priority-work",
            "title": f"Continue priority work for {objective.code}",
            "reason": "No blocking signal was detected; keep the highest-value current work moving.",
            "business_outcome": f"Progress continues toward {objective.name} with visible next evidence.",
            "acceptance_criteria": ["The next progress artifact or decision is recorded with evidence."],
        }
    ]


def propose_next_actions_for_objective(payload: dict, *, objective_id: str, actor_id: str, correlation_id: str) -> list[Task]:
    try:
        objective = Objective.objects.get(id=objective_id, status=Objective.Status.ACTIVE)
    except Objective.DoesNotExist as exc:
        raise CosObjectiveNotFoundError("Active objective was not found.") from exc

    requested_limit = int(payload.get("limit", 1))
    if requested_limit < 1 or requested_limit > 5:
        raise InvalidCosPlanningPayloadError("limit must be between 1 and 5.")

    proposals = recommend_next_actions_for_objective(objective_health(objective))[:requested_limit]
    return propose_work_for_objective(
        {"mode": "QUICK", "proposals": proposals},
        objective_id=str(objective.id),
        actor_id=actor_id,
        correlation_id=correlation_id,
    )


def propose_work_for_objective(payload: dict, *, objective_id: str, actor_id: str, correlation_id: str) -> list[Task]:
    mode = str(payload.get("mode", "STANDARD")).strip()
    if mode not in {"QUICK", "STANDARD"}:
        raise InvalidCosPlanningPayloadError("mode must be QUICK or STANDARD.")
    proposals = payload.get("proposals")
    actor = actor_id.strip() or "api"

    try:
        objective = Objective.objects.get(id=objective_id, status=Objective.Status.ACTIVE)
    except Objective.DoesNotExist as exc:
        raise CosObjectiveNotFoundError("Active objective was not found.") from exc

    if proposals is None:
        proposals = [
            {
                "key": "map-current-state",
                "title": f"Map current state for {objective.code}",
                "business_outcome": f"Current blockers, assets and open decisions for {objective.name} are visible.",
                "acceptance_criteria": ["Current status, blockers and next decisions are documented."],
            },
            {
                "key": "define-next-milestone",
                "title": f"Define next milestone for {objective.code}",
                "business_outcome": f"The next measurable milestone for {objective.name} is clear and actionable.",
                "acceptance_criteria": ["Milestone, owner, due date assumption and verification evidence are documented."],
            },
        ]
        if mode == "STANDARD":
            proposals.append(
                {
                    "key": "risk-review",
                    "title": f"Review risks for {objective.code}",
                    "business_outcome": f"High-impact risks for {objective.name} have mitigation tasks or explicit acceptance.",
                    "acceptance_criteria": ["Top risks, likelihood, impact and mitigation owner are documented."],
                }
            )

    if not isinstance(proposals, list) or not proposals:
        raise InvalidCosPlanningPayloadError("proposals must be a non-empty list.")
    if len(proposals) > 10:
        raise InvalidCosPlanningPayloadError("At most 10 proposals can be created at once.")

    tasks: list[Task] = []
    for index, proposal in enumerate(proposals):
        if not isinstance(proposal, dict):
            raise InvalidCosPlanningPayloadError("Each proposal must be an object.")
        title = str(proposal.get("title", "")).strip()
        key = str(proposal.get("key", f"proposal-{index + 1}")).strip()
        business_outcome = str(proposal.get("business_outcome", "")).strip()
        criteria = proposal.get("acceptance_criteria", [])
        if not title or not business_outcome:
            raise InvalidCosPlanningPayloadError("Each proposal requires title and business_outcome.")
        if not isinstance(criteria, list) or not criteria:
            raise InvalidCosPlanningPayloadError("Each proposal requires at least one acceptance criterion.")
        criteria_payload = []
        for criterion in criteria:
            description = str(criterion).strip()
            if not description:
                raise InvalidCosPlanningPayloadError("Acceptance criteria cannot be empty.")
            criteria_payload.append(
                {
                    "description": description,
                    "criterion_type": AcceptanceCriterion.CriterionType.MANUAL,
                    "required": True,
                }
            )
        task, _created = upsert_task(
            {
                "objective_id": str(objective.id),
                "external_key": f"cos-objective:{objective.id}:{key}",
                "title": title,
                "business_outcome": business_outcome,
                "acceptance_criteria": criteria_payload,
            },
            actor_id=actor,
            correlation_id=correlation_id,
        )
        tasks.append(task)

    AuditEvent.objects.create(
        actor_type=AuditEvent.ActorType.SYSTEM,
        actor_id=actor,
        action="cos.objective.work_proposed",
        object_type="portfolio.Objective",
        object_id=str(objective.id),
        correlation_id=correlation_id,
        metadata={
            "mode": mode,
            "task_count": len(tasks),
            "no_external_action": True,
        },
    )
    return tasks


def serialize_approval_summary(approval: ApprovalRequest) -> dict:
    return {
        "id": str(approval.id),
        "subject_type": approval.subject_type,
        "subject_id": approval.subject_id,
        "subject_version": approval.subject_version,
        "action": approval.action,
        "status": approval.status,
        "expires_at": approval.expires_at.isoformat(),
    }


def weekly_review() -> dict:
    now = timezone.now()
    active_objectives = Objective.objects.filter(status=Objective.Status.ACTIVE).order_by("code")
    tasks = Task.objects.select_related("objective").all()
    open_tasks = tasks.exclude(status__in=[Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.FAILED])
    pending_approvals = ApprovalRequest.objects.filter(status=ApprovalRequest.Status.PENDING).order_by("expires_at")
    blocked_tasks = open_tasks.filter(status=Task.Status.BLOCKED).order_by("-updated_at")
    unverified_tasks = open_tasks.filter(status=Task.Status.DELIVERED_UNVERIFIED).order_by("-updated_at")
    verifying_tasks = open_tasks.filter(status=Task.Status.VERIFYING).order_by("-updated_at")
    completed_tasks = tasks.filter(status=Task.Status.COMPLETED).order_by("-updated_at")
    recent_audit_events = AuditEvent.objects.all()[:20]

    risks: list[dict[str, str | int]] = []
    if pending_approvals.exists():
        risks.append({"level": "HIGH", "text": "Pending approvals require CEO or delegated decision.", "count": pending_approvals.count()})
    if blocked_tasks.exists():
        risks.append({"level": "HIGH", "text": "Blocked tasks may delay active objectives.", "count": blocked_tasks.count()})
    if unverified_tasks.exists():
        risks.append({"level": "MEDIUM", "text": "Delivered work is waiting for verification.", "count": unverified_tasks.count()})
    if not active_objectives.exists():
        risks.append({"level": "HIGH", "text": "No active objectives are currently registered.", "count": 0})

    next_actions: list[str] = []
    if pending_approvals.exists():
        next_actions.append("Review pending approvals.")
    if blocked_tasks.exists():
        next_actions.append("Resolve or reassign blocked tasks.")
    if unverified_tasks.exists() or verifying_tasks.exists():
        next_actions.append("Verify delivered work against acceptance criteria and evidence.")
    if not next_actions:
        next_actions.append("Confirm next priority and keep execution moving.")

    return {
        "generated_at": now,
        "counts": {
            "active_objectives": active_objectives.count(),
            "open_tasks": open_tasks.count(),
            "pending_approvals": pending_approvals.count(),
            "blocked_tasks": blocked_tasks.count(),
            "unverified_deliveries": unverified_tasks.count(),
            "verifying_tasks": verifying_tasks.count(),
            "completed_tasks": completed_tasks.count(),
        },
        "active_objectives": list(active_objectives[:10]),
        "pending_approvals": list(pending_approvals[:10]),
        "blocked_tasks": list(blocked_tasks[:10]),
        "unverified_tasks": list(unverified_tasks[:10]),
        "verifying_tasks": list(verifying_tasks[:10]),
        "completed_tasks": list(completed_tasks[:10]),
        "recent_audit_events": list(recent_audit_events),
        "risks": risks,
        "next_actions": next_actions,
    }


def serialize_weekly_review(review: dict) -> dict:
    return {
        "generated_at": review["generated_at"].isoformat(),
        "counts": review["counts"],
        "active_objectives": [
            {
                "id": str(objective.id),
                "code": objective.code,
                "name": objective.name,
                "business_outcome": objective.business_outcome,
                "owner_agent_id": objective.owner_agent_id,
                "due_at": objective.due_at.isoformat() if objective.due_at else None,
            }
            for objective in review["active_objectives"]
        ],
        "pending_approvals": [serialize_approval_summary(approval) for approval in review["pending_approvals"]],
        "blocked_tasks": [serialize_task_summary(task) for task in review["blocked_tasks"]],
        "unverified_tasks": [serialize_task_summary(task) for task in review["unverified_tasks"]],
        "verifying_tasks": [serialize_task_summary(task) for task in review["verifying_tasks"]],
        "completed_tasks": [serialize_task_summary(task) for task in review["completed_tasks"]],
        "risks": review["risks"],
        "next_actions": review["next_actions"],
    }


def intake_request(payload: dict, *, idempotency_key: str, correlation_id: str, actor_id: str = "api") -> tuple[dict, int]:
    idempotency_key = idempotency_key.strip()
    correlation_id = correlation_id.strip()
    actor_id = actor_id.strip() or "api"
    if not idempotency_key.strip() or not correlation_id.strip():
        raise MissingHeaderError("Idempotency-Key and X-Correlation-ID are required.")

    title = str(payload.get("title", "")).strip()
    objective_id = str(payload.get("objective_id", "")).strip()
    business_outcome = str(payload.get("business_outcome", "")).strip()

    if not title or not objective_id:
        raise InvalidPayloadError("title and objective_id are required.")

    request_hash = canonical_hash(payload)
    existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
    if existing:
        if existing.request_hash != request_hash:
            raise IdempotencyConflictError("Idempotency key was already used for a different request.")
        return existing.response_payload, existing.status_code

    try:
        with transaction.atomic():
            objective = Objective.objects.select_for_update().get(id=objective_id, status=Objective.Status.ACTIVE)
            task = Task.objects.create(
                objective=objective,
                title=title,
                business_outcome=business_outcome,
                status=Task.Status.DRAFT,
                created_by=actor_id,
            )
            AuditEvent.objects.create(
                actor_type=AuditEvent.ActorType.SYSTEM,
                actor_id=actor_id,
                action="cos.intake.task_created",
                object_type="operations.Task",
                object_id=str(task.id),
                correlation_id=correlation_id,
                metadata={"objective_id": str(objective.id), "task_status": task.status},
            )
            response = {
                "task_id": str(task.id),
                "correlation_id": correlation_id,
                "status": task.status,
            }
            IdempotencyRecord.objects.create(
                key=idempotency_key,
                request_hash=request_hash,
                response_payload=response,
                status_code=201,
            )
    except Objective.DoesNotExist as exc:
        raise ObjectiveNotFoundError("Active objective was not found.") from exc
    except IntegrityError as exc:
        raise IdempotencyConflictError("Duplicate idempotency key.") from exc

    return response, 201
