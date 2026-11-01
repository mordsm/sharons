from django.utils import timezone

from executive_assistant.services import create_executive_brief
from operations.models import AgentRun, Evidence, Task
from operations.services import invoke_agent, record_task_evidence, transition_task
from marketing.services import create_marketing_request
from product.services import product_manager_status
from project_manager.services import create_execution_review


class AgentRunnerError(Exception):
    code = "AGENT_RUNNER_FAILED"


RUNNERS = {"product_manager", "project_manager", "executive_assistant", "marketing"}


def execute_assigned_agent(payload: dict, *, actor_id: str, correlation_id: str) -> AgentRun:
    agent_run = invoke_agent(payload, actor_id=actor_id, correlation_id=correlation_id)
    task = agent_run.task
    try:
        if agent_run.agent_id not in RUNNERS:
            raise AgentRunnerError("This agent has no internal runner.")
        output = _run(
            agent_run.agent_id,
            task,
            actor_id=actor_id,
            correlation_id=correlation_id,
            input_snapshot=agent_run.input_snapshot,
        )
        evidence = record_task_evidence(
            {
                "kind": Evidence.Kind.ARTIFACT,
                "uri_or_reference": f"agent-run:{agent_run.id}",
                "metadata": {"agent_id": agent_run.agent_id, "external_action": False},
            },
            task_id=str(task.id),
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        task.refresh_from_db()
        if task.status == Task.Status.ASSIGNED:
            task = transition_task(
                str(task.id),
                to_status=Task.Status.IN_PROGRESS,
                expected_version=task.version,
                actor_id=actor_id,
                correlation_id=correlation_id,
            )
        if task.status == Task.Status.IN_PROGRESS:
            task = transition_task(
                str(task.id),
                to_status=Task.Status.DELIVERED_UNVERIFIED,
                expected_version=task.version,
                actor_id=actor_id,
                correlation_id=correlation_id,
            )
        agent_run.status = AgentRun.Status.COMPLETED
        agent_run.output = {**output, "evidence_id": str(evidence.id), "task_status": task.status, "external_action": False}
        agent_run.completed_at = timezone.now()
        agent_run.save(update_fields=["status", "output", "completed_at"])
    except Exception as exc:
        agent_run.status = AgentRun.Status.FAILED
        agent_run.output = {"error": exc.__class__.__name__, "external_action": False}
        agent_run.completed_at = timezone.now()
        agent_run.save(update_fields=["status", "output", "completed_at"])
        raise
    return agent_run


def _marketing_payload(task: Task, input_snapshot: dict) -> dict:
    from portfolio.models import ObjectiveProjectLink

    payload = {
        "objective": str(input_snapshot.get("objective") or task.title).strip(),
        "objective_id": str(task.objective_id),
        "time_horizon": str(input_snapshot.get("time_horizon") or "30 days").strip() or "30 days",
        "requested_action": "STRATEGY",
    }
    for key in ("geography", "currency", "budget_amount", "project_id"):
        value = input_snapshot.get(key)
        if value not in (None, "", []):
            payload[key] = value
    if "project_id" not in payload:
        link = (
            ObjectiveProjectLink.objects.filter(objective_id=task.objective_id, active=True)
            .select_related("project")
            .order_by("role")
            .first()
        )
        if link is not None:
            payload["project_id"] = str(link.project_id)
    return payload


def _run(agent_id: str, task: Task, *, actor_id: str, correlation_id: str, input_snapshot: dict | None = None) -> dict:
    if agent_id == "product_manager":
        status = product_manager_status()
        return {
            "action": "product_status",
            "project_count": len(status["projects"]),
            "external_write_enabled": False,
        }
    if agent_id == "marketing":
        marketing_request = create_marketing_request(
            _marketing_payload(task, input_snapshot or {}),
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        return {
            "action": "marketing_plan",
            "marketing_request_id": str(marketing_request.id),
            "external_action_enabled": False,
            "ad_spend_enabled": False,
            "social_publish_enabled": False,
        }
    if agent_id == "project_manager":
        review = create_execution_review(
            {"objective_id": str(task.objective_id)},
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        return {
            "action": "execution_review",
            "execution_review_id": str(review.id),
            "external_action_enabled": False,
        }
    brief = create_executive_brief(
        {"title": task.title, "brief_type": "WEEKLY_REVIEW_PREP"},
        actor_id=actor_id,
        correlation_id=correlation_id,
    )
    return {
        "action": "executive_brief",
        "brief_id": str(brief.id),
        "no_external_send": brief.no_external_send,
    }
