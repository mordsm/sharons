import json

import pytest

from governance.models import AuditEvent
from operations.models import AcceptanceCriterion, Task
from portfolio.models import Objective, StrategyVersion


pytestmark = pytest.mark.django_db


def headers(key: str = "cos-work-1") -> dict:
    return {"Idempotency-Key": key, "X-Correlation-ID": f"corr-{key}", "X-Actor-ID": "chief_of_staff"}


@pytest.fixture
def active_objective():
    strategy = StrategyVersion.objects.create(version=1, title="90 day plan", content={}, status=StrategyVersion.Status.ACTIVE)
    return Objective.objects.create(
        code="O1",
        strategy_version=strategy,
        name="Mental Trainer commercial readiness",
        business_outcome="Prepare beta launch.",
        status=Objective.Status.ACTIVE,
    )


def test_cos_objective_work_propose_creates_default_draft_tasks(client, active_objective):
    response = client.post(
        f"/api/v1/cos/objectives/{active_objective.id}/work/propose/",
        data=json.dumps({"mode": "STANDARD"}),
        content_type="application/json",
        headers=headers(),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["no_external_action"] is True
    assert len(body["tasks"]) == 3
    assert Task.objects.filter(objective=active_objective, status=Task.Status.DRAFT).count() == 3
    assert AcceptanceCriterion.objects.filter(task__objective=active_objective, required=True).count() == 3
    assert AuditEvent.objects.filter(
        action="cos.objective.work_proposed",
        correlation_id="corr-cos-work-1",
        metadata__no_external_action=True,
        metadata__task_count=3,
    ).exists()


def test_cos_objective_work_propose_accepts_custom_proposals(client, active_objective):
    response = client.post(
        f"/api/v1/cos/objectives/{active_objective.id}/work/propose/",
        data=json.dumps(
            {
                "mode": "QUICK",
                "proposals": [
                    {
                        "key": "beta-readiness",
                        "title": "Prepare beta readiness checklist",
                        "business_outcome": "Beta launch readiness can be reviewed in one place.",
                        "acceptance_criteria": ["Checklist exists with owner, status and open risks."],
                    }
                ],
            }
        ),
        content_type="application/json",
        headers=headers("cos-work-2"),
    )

    assert response.status_code == 201
    body = response.json()["tasks"]
    assert len(body) == 1
    assert body[0]["title"] == "Prepare beta readiness checklist"
    task = Task.objects.get(external_key=f"cos-objective:{active_objective.id}:beta-readiness")
    assert task.acceptance_criteria.get().description == "Checklist exists with owner, status and open risks."


def test_cos_objective_work_propose_is_idempotent(client, active_objective):
    payload = {"mode": "QUICK"}
    url = f"/api/v1/cos/objectives/{active_objective.id}/work/propose/"

    first = client.post(url, data=json.dumps(payload), content_type="application/json", headers=headers("cos-work-3"))
    second = client.post(url, data=json.dumps(payload), content_type="application/json", headers=headers("cos-work-3"))

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()
    assert Task.objects.filter(objective=active_objective).count() == 2
    assert AuditEvent.objects.filter(action="cos.objective.work_proposed").count() == 1


def test_cos_objective_work_propose_rejects_bad_payload(client, active_objective):
    response = client.post(
        f"/api/v1/cos/objectives/{active_objective.id}/work/propose/",
        data=json.dumps({"mode": "DEEP"}),
        content_type="application/json",
        headers=headers("cos-work-4"),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_COS_PLANNING_PAYLOAD"
    assert Task.objects.count() == 0


def test_cos_objective_work_propose_requires_active_objective(client):
    response = client.post(
        "/api/v1/cos/objectives/00000000-0000-0000-0000-000000000000/work/propose/",
        data=json.dumps({"mode": "QUICK"}),
        content_type="application/json",
        headers=headers("cos-work-5"),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "OBJECTIVE_NOT_FOUND"
