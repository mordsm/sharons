from django.db import transaction

from core.services import objective_health, serialize_task_summary
from governance.models import AuditEvent
from operations.models import AcceptanceCriterion, AgentDefinition, Task
from operations.services import upsert_task
from portfolio.models import Objective
from project_manager.models import BlockerReview, ExecutionReview, MilestoneProposal


class ProjectManagerError(Exception):
    code = "PROJECT_MANAGER_ERROR"


class InvalidProjectManagerPayloadError(ProjectManagerError):
    code = "INVALID_PROJECT_MANAGER_PAYLOAD"


class ProjectManagerBlockedError(ProjectManagerError):
    code = "PROJECT_MANAGER_BLOCKED"


def serialize_execution_review(review: ExecutionReview) -> dict:
    return {
        "id": str(review.id),
        "objective_id": str(review.objective_id),
        "summary": review.summary,
        "health_status": review.health_status,
        "risks": review.risks,
        "recommendations": review.recommendations,
        "task_snapshot": review.task_snapshot,
        "status": review.status,
        "no_external_action": review.no_external_action,
        "created_by": review.created_by,
        "created_at": review.created_at.isoformat(),
    }


def serialize_milestone_proposal(proposal: MilestoneProposal) -> dict:
    return {
        "id": str(proposal.id),
        "objective_id": str(proposal.objective_id),
        "task_id": str(proposal.task_id),
        "title": proposal.title,
        "rationale": proposal.rationale,
        "status": proposal.status,
        "no_external_action": proposal.no_external_action,
        "created_by": proposal.created_by,
        "created_at": proposal.created_at.isoformat(),
    }


def serialize_blocker_review(review: BlockerReview) -> dict:
    return {
        "id": str(review.id),
        "task_id": str(review.task_id),
        "blocker_summary": review.blocker_summary,
        "recommended_action": review.recommended_action,
        "escalation_required": review.escalation_required,
        "no_external_action": review.no_external_action,
        "created_by": review.created_by,
        "created_at": review.created_at.isoformat(),
    }


def project_manager_status() -> dict:
    return {
        "agent_id": "project_manager",
        "agent_registered": AgentDefinition.objects.filter(agent_id="project_manager", active=True).exists(),
        "external_action_enabled": False,
        "execution_reviews": ExecutionReview.objects.count(),
        "milestone_proposals": MilestoneProposal.objects.count(),
        "blocker_reviews": BlockerReview.objects.count(),
        "blocked_tasks": Task.objects.filter(status=Task.Status.BLOCKED).count(),
    }


def create_execution_review(payload: dict, *, actor_id: str, correlation_id: str) -> ExecutionReview:
    objective_id = str(payload.get("objective_id", "")).strip()
    if not objective_id:
        raise InvalidProjectManagerPayloadError("objective_id is required.")
    actor = actor_id.strip() or "api"
    with transaction.atomic():
        objective = Objective.objects.select_for_update().get(id=objective_id, status=Objective.Status.ACTIVE)
        health = objective_health(objective)
        open_tasks = objective.tasks.exclude(status__in=[Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.FAILED]).order_by("-updated_at")
        blocked = open_tasks.filter(status=Task.Status.BLOCKED)
        unverified = open_tasks.filter(status=Task.Status.DELIVERED_UNVERIFIED)
        recommendations = []
        risks = []
        if blocked.exists():
            risks.append({"level": "HIGH", "text": "Blocked tasks require unblock decision.", "count": blocked.count()})
            recommendations.append({"action": "REVIEW_BLOCKERS", "reason": "Blocked work is delaying the objective."})
        if unverified.exists():
            risks.append({"level": "MEDIUM", "text": "Delivered work is waiting for verification.", "count": unverified.count()})
            recommendations.append({"action": "VERIFY_DELIVERIES", "reason": "Progress cannot be counted until evidence is verified."})
        if not recommendations:
            recommendations.append({"action": "CONTINUE_EXECUTION", "reason": "No major coordination risk detected."})
        review = ExecutionReview.objects.create(
            objective=objective,
            summary=f"{objective.code}: {health['status']} with {open_tasks.count()} open tasks.",
            health_status=health["status"],
            risks=risks,
            recommendations=recommendations,
            task_snapshot={
                "open_tasks": open_tasks.count(),
                "blocked_tasks": blocked.count(),
                "unverified_deliveries": unverified.count(),
                "recent_open_tasks": [serialize_task_summary(task) for task in open_tasks[:10]],
            },
            no_external_action=True,
            created_by=actor,
        )
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="project_manager.execution_review.created",
            object_type="project_manager.ExecutionReview",
            object_id=str(review.id),
            correlation_id=correlation_id,
            metadata={"objective_id": str(objective.id), "health_status": review.health_status, "no_external_action": True},
        )
    return review


def propose_milestones(payload: dict, *, objective_id: str, actor_id: str, correlation_id: str) -> list[MilestoneProposal]:
    milestones = payload.get("milestones")
    if milestones is None:
        milestones = [
            {
                "key": "execution-sequence",
                "title": "Confirm execution sequence",
                "rationale": "A visible sequence reduces coordination drift.",
            },
            {
                "key": "risk-and-blocker-review",
                "title": "Review risks and blockers",
                "rationale": "Active risks need an owner and a next action.",
            },
        ]
    if not isinstance(milestones, list) or not milestones:
        raise InvalidProjectManagerPayloadError("milestones must be a non-empty list.")
    actor = actor_id.strip() or "api"
    with transaction.atomic():
        objective = Objective.objects.select_for_update().get(id=objective_id, status=Objective.Status.ACTIVE)
        proposals = []
        for index, milestone in enumerate(milestones):
            if not isinstance(milestone, dict):
                raise InvalidProjectManagerPayloadError("Each milestone must be an object.")
            title = str(milestone.get("title", "")).strip()
            rationale = str(milestone.get("rationale", "")).strip()
            key = str(milestone.get("key", f"milestone-{index + 1}")).strip()
            if not title or not rationale:
                raise InvalidProjectManagerPayloadError("Each milestone requires title and rationale.")
            task, _created = upsert_task(
                {
                    "objective_id": str(objective.id),
                    "external_key": f"project-manager:{objective.id}:{key}",
                    "title": title,
                    "business_outcome": rationale,
                    "acceptance_criteria": [
                        {
                            "description": f"Milestone is reviewed and either accepted, revised or dismissed: {title}",
                            "criterion_type": AcceptanceCriterion.CriterionType.MANUAL,
                            "required": True,
                        }
                    ],
                },
                actor_id=actor,
                correlation_id=correlation_id,
            )
            proposal, _ = MilestoneProposal.objects.get_or_create(
                objective=objective,
                task=task,
                defaults={"title": title, "rationale": rationale, "created_by": actor, "no_external_action": True},
            )
            proposals.append(proposal)
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="project_manager.milestones.proposed",
            object_type="portfolio.Objective",
            object_id=str(objective.id),
            correlation_id=correlation_id,
            metadata={"milestone_count": len(proposals), "no_external_action": True},
        )
    return proposals


def create_blocker_review(payload: dict, *, task_id: str, actor_id: str, correlation_id: str) -> BlockerReview:
    recommended_action = str(payload.get("recommended_action", "ESCALATE_OR_REASSIGN")).strip()
    blocker_summary = str(payload.get("blocker_summary", "")).strip()
    escalation_required = bool(payload.get("escalation_required", True))
    if not blocker_summary:
        raise InvalidProjectManagerPayloadError("blocker_summary is required.")
    actor = actor_id.strip() or "api"
    with transaction.atomic():
        task = Task.objects.select_for_update().get(id=task_id)
        if task.status != Task.Status.BLOCKED:
            raise ProjectManagerBlockedError("Blocker reviews require a BLOCKED task.")
        review = BlockerReview.objects.create(
            task=task,
            blocker_summary=blocker_summary,
            recommended_action=recommended_action,
            escalation_required=escalation_required,
            no_external_action=True,
            created_by=actor,
        )
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="project_manager.blocker_review.created",
            object_type="project_manager.BlockerReview",
            object_id=str(review.id),
            correlation_id=correlation_id,
            metadata={"task_id": str(task.id), "recommended_action": recommended_action, "no_external_action": True},
        )
    return review

