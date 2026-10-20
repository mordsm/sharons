import json

import pytest

from governance.models import AuditEvent
from operations.models import Task
from portfolio.models import Objective, StrategyVersion
from project_manager.models import BlockerReview, ExecutionReview, MilestoneProposal


pytestmark = pytest.mark.django_db


def headers(key: str = "pm-1") -> dict:
    return {"Idempotency-Key": key, "X-Correlation-ID": f"corr-{key}", "X-Actor-ID": "project_manager"}


@pytest.fixture
def active_objective():
    strategy = StrategyVersion.objects.create(version=1, title="90 day plan", content={}, status=StrategyVersion.Status.ACTIVE)
    return Objective.objects.create(
        code="O1",
        strategy_version=strategy,
        name="Mental Trainer readiness",
        business_outcome="Ready for beta.",
        status=Objective.Status.ACTIVE,
    )


def test_execution_review_create_summarizes_objective_and_audits(client, active_objective):
    Task.objects.create(objective=active_objective, title="Blocked beta task", status=Task.Status.BLOCKED, created_by="test")
    Task.objects.create(objective=active_objective, title="Delivered task", status=Task.Status.DELIVERED_UNVERIFIED, created_by="test")

    response = client.post(
        "/api/v1/project-manager/execution-reviews/create/",
        data=json.dumps({"objective_id": str(active_objective.id)}),
        content_type="application/json",
        headers=headers("pm-review-1"),
    )

    assert response.status_code == 201
    review = response.json()["execution_review"]
    assert review["health_status"] == "BLOCKED"
    assert review["task_snapshot"]["blocked_tasks"] == 1
    assert review["no_external_action"] is True
    assert ExecutionReview.objects.count() == 1
    assert AuditEvent.objects.filter(action="project_manager.execution_review.created", correlation_id="corr-pm-review-1").exists()


def test_milestones_propose_creates_internal_draft_tasks_idempotently(client, active_objective):
    payload = {
        "milestones": [
            {"key": "beta-sequence", "title": "Sequence beta launch tasks", "rationale": "Launch tasks need a clear order."}
        ]
    }
    url = f"/api/v1/project-manager/objectives/{active_objective.id}/milestones/propose/"

    first = client.post(url, data=json.dumps(payload), content_type="application/json", headers=headers("pm-ms-1"))
    second = client.post(url, data=json.dumps(payload), content_type="application/json", headers=headers("pm-ms-1"))

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()
    proposal = MilestoneProposal.objects.get()
    assert proposal.no_external_action is True
    assert proposal.task.status == Task.Status.DRAFT
    assert proposal.task.external_key == f"project-manager:{active_objective.id}:beta-sequence"
    assert AuditEvent.objects.filter(action="project_manager.milestones.proposed", metadata__milestone_count=1).count() == 1


def test_blocker_review_create_requires_blocked_task_and_audits(client, active_objective):
    task = Task.objects.create(objective=active_objective, title="Blocked implementation", status=Task.Status.BLOCKED, created_by="test")

    response = client.post(
        f"/api/v1/project-manager/tasks/{task.id}/blocker-review/create/",
        data=json.dumps({"blocker_summary": "Waiting on acceptance decision.", "recommended_action": "ESCALATE_TO_COS"}),
        content_type="application/json",
        headers=headers("pm-blocker-1"),
    )

    assert response.status_code == 201
    review = response.json()["blocker_review"]
    assert review["recommended_action"] == "ESCALATE_TO_COS"
    assert review["escalation_required"] is True
    assert BlockerReview.objects.count() == 1
    assert AuditEvent.objects.filter(action="project_manager.blocker_review.created", object_id=review["id"]).exists()


def test_blocker_review_rejects_unblocked_task(client, active_objective):
    task = Task.objects.create(objective=active_objective, title="Normal task", status=Task.Status.IN_PROGRESS, created_by="test")

    response = client.post(
        f"/api/v1/project-manager/tasks/{task.id}/blocker-review/create/",
        data=json.dumps({"blocker_summary": "Not actually blocked."}),
        content_type="application/json",
        headers=headers("pm-blocker-2"),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PROJECT_MANAGER_BLOCKED"


def test_project_manager_status_reports_internal_boundaries(client, active_objective):
    Task.objects.create(objective=active_objective, title="Blocked task", status=Task.Status.BLOCKED, created_by="test")
    ExecutionReview.objects.create(objective=active_objective, summary="Review", health_status="BLOCKED", created_by="test")

    response = client.get("/api/v1/project-manager/status/")

    assert response.status_code == 200
    status = response.json()["status"]
    assert status["agent_id"] == "project_manager"
    assert status["external_action_enabled"] is False
    assert status["execution_reviews"] == 1
    assert status["blocked_tasks"] == 1

