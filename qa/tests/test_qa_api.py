import json

import pytest

from governance.models import AuditEvent
from operations.models import AcceptanceCriterion, Evidence, Task
from portfolio.models import Objective, StrategyVersion
from qa.models import VerificationReview


pytestmark = pytest.mark.django_db


def headers(key: str = "qa-1") -> dict:
    return {"Idempotency-Key": key, "X-Correlation-ID": f"corr-{key}", "X-Actor-ID": "qa_agent"}


@pytest.fixture
def active_objective():
    strategy = StrategyVersion.objects.create(version=1, title="90 day plan", content={}, status=StrategyVersion.Status.ACTIVE)
    return Objective.objects.create(
        code="O4",
        strategy_version=strategy,
        name="Rules Engine",
        business_outcome="Validated rules workflows.",
        status=Objective.Status.ACTIVE,
    )


@pytest.fixture
def delivered_task(active_objective):
    task = Task.objects.create(
        objective=active_objective,
        title="Assess rules evaluator",
        status=Task.Status.DELIVERED_UNVERIFIED,
        created_by="developer",
    )
    AcceptanceCriterion.objects.create(task=task, description="Evidence names concrete files and first reuse gaps.")
    Evidence.objects.create(task=task, kind=Evidence.Kind.ARTIFACT, uri_or_reference="rules_engine/compass_rules.py", verified=False, created_by="developer")
    return task


def test_qa_verification_queue_lists_delivered_unverified(client, delivered_task):
    response = client.get("/api/v1/qa/verification-queue/")

    assert response.status_code == 200
    assert response.json()["tasks"][0]["id"] == str(delivered_task.id)


def test_qa_review_accepts_evidence_and_moves_task_to_verifying_idempotently(client, delivered_task):
    payload = {"decision": VerificationReview.Decision.ACCEPTED, "notes": "Evidence is sufficient.", "mark_passed": True}
    url = f"/api/v1/qa/tasks/{delivered_task.id}/review/"

    first = client.post(url, data=json.dumps(payload), content_type="application/json", headers=headers("qa-review-1"))
    second = client.post(url, data=json.dumps(payload), content_type="application/json", headers=headers("qa-review-1"))

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    delivered_task.refresh_from_db()
    assert delivered_task.status == Task.Status.VERIFYING
    assert delivered_task.evidence.get().verified is True
    assert delivered_task.acceptance_criteria.get().status == AcceptanceCriterion.Status.PASSED
    assert VerificationReview.objects.filter(task=delivered_task, decision=VerificationReview.Decision.ACCEPTED).count() == 1
    assert AuditEvent.objects.filter(action="qa.verification_review.created", metadata__decision=VerificationReview.Decision.ACCEPTED).exists()


def test_qa_review_rejects_non_queue_task(client, active_objective):
    task = Task.objects.create(objective=active_objective, title="In progress", status=Task.Status.IN_PROGRESS, created_by="developer")

    response = client.post(
        f"/api/v1/qa/tasks/{task.id}/review/",
        data=json.dumps({"decision": VerificationReview.Decision.ACCEPTED}),
        content_type="application/json",
        headers=headers("qa-review-2"),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "QA_BLOCKED"


def test_qa_status_reports_boundaries(client, delivered_task):
    response = client.get("/api/v1/qa/status/")

    assert response.status_code == 200
    status = response.json()["status"]
    assert status["agent_id"] == "qa"
    assert status["external_action_enabled"] is False
    assert status["verification_queue"] == 1

