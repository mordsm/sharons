import json

import pytest
from django.utils import timezone

from governance.models import AuditEvent
from operations.models import AcceptanceCriterion, Plan, Task
from portfolio.models import Objective, StrategyVersion


@pytest.fixture
def active_objective():
    strategy = StrategyVersion.objects.create(
        version=1,
        title="Initial strategy",
        content={"horizon": "90 days"},
        status=StrategyVersion.Status.ACTIVE,
        valid_from=timezone.now(),
    )
    return Objective.objects.create(
        code="O1",
        strategy_version=strategy,
        name="Mental Trainer commercial readiness",
        business_outcome="Ready for beta",
        status=Objective.Status.ACTIVE,
        owner_agent_id="chief_of_staff",
    )


@pytest.mark.django_db
def test_task_upsert_creates_draft_task_with_acceptance_criteria(client, active_objective):
    response = client.post(
        "/api/v1/tasks/upsert/",
        data=json.dumps(
            {
                "objective_id": str(active_objective.id),
                "external_key": "beta-checklist",
                "title": "Prepare beta checklist",
                "business_outcome": "Beta review is ready",
                "acceptance_criteria": [{"description": "Checklist covers desktop and mobile"}],
            }
        ),
        content_type="application/json",
        headers={"Idempotency-Key": "upsert-1", "X-Correlation-ID": "corr-upsert-1"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["created"] is True
    assert body["task"]["status"] == Task.Status.DRAFT
    assert body["task"]["acceptance_criteria"][0]["description"] == "Checklist covers desktop and mobile"
    assert Task.objects.count() == 1
    assert AcceptanceCriterion.objects.count() == 1
    assert AuditEvent.objects.filter(action="operations.task.upserted", correlation_id="corr-upsert-1").exists()


@pytest.mark.django_db
def test_task_upsert_updates_existing_task_by_external_key(client, active_objective):
    task = Task.objects.create(
        objective=active_objective,
        external_key="beta-checklist",
        title="Old title",
        created_by="test",
    )

    response = client.post(
        "/api/v1/tasks/upsert/",
        data=json.dumps(
            {
                "objective_id": str(active_objective.id),
                "external_key": "beta-checklist",
                "title": "Updated title",
                "acceptance_criteria": [{"description": "Updated criterion"}],
            }
        ),
        content_type="application/json",
        headers={"Idempotency-Key": "upsert-2", "X-Correlation-ID": "corr-upsert-2"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["created"] is False
    task.refresh_from_db()
    assert task.title == "Updated title"
    assert task.version == 2
    assert task.acceptance_criteria.get().description == "Updated criterion"


@pytest.mark.django_db
def test_task_upsert_is_idempotent(client, active_objective):
    payload = {
        "objective_id": str(active_objective.id),
        "external_key": "beta-checklist",
        "title": "Prepare beta checklist",
    }
    headers = {"Idempotency-Key": "upsert-3", "X-Correlation-ID": "corr-upsert-3"}

    first = client.post("/api/v1/tasks/upsert/", data=json.dumps(payload), content_type="application/json", headers=headers)
    second = client.post("/api/v1/tasks/upsert/", data=json.dumps(payload), content_type="application/json", headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()
    assert Task.objects.count() == 1
    assert AuditEvent.objects.count() == 1


@pytest.mark.django_db
def test_task_upsert_rejects_empty_acceptance_criterion(client, active_objective):
    response = client.post(
        "/api/v1/tasks/upsert/",
        data=json.dumps(
            {
                "objective_id": str(active_objective.id),
                "title": "Prepare beta checklist",
                "acceptance_criteria": [{"description": "   "}],
            }
        ),
        content_type="application/json",
        headers={"Idempotency-Key": "upsert-4", "X-Correlation-ID": "corr-upsert-4"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_TASK_UPSERT_PAYLOAD"
    assert Task.objects.count() == 0


@pytest.mark.django_db
def test_task_upsert_links_to_plan(client, active_objective):
    plan = Plan.objects.create(objective=active_objective, name="Launch plan", created_by="test")

    response = client.post(
        "/api/v1/tasks/upsert/",
        data=json.dumps(
            {
                "objective_id": str(active_objective.id),
                "plan_id": str(plan.id),
                "title": "Prepare beta checklist",
            }
        ),
        content_type="application/json",
        headers={"Idempotency-Key": "upsert-5", "X-Correlation-ID": "corr-upsert-5"},
    )

    assert response.status_code == 201
    assert response.json()["task"]["plan_id"] == str(plan.id)
