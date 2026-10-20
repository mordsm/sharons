import json

import pytest

from governance.models import AuditEvent
from operations.models import Task
from portfolio.models import Objective, StrategyVersion


pytestmark = pytest.mark.django_db


def headers(key: str = "cos-next-1") -> dict:
    return {"Idempotency-Key": key, "X-Correlation-ID": f"corr-{key}", "X-Actor-ID": "chief_of_staff"}


@pytest.fixture
def strategy():
    return StrategyVersion.objects.create(version=1, title="90 day plan", content={}, status=StrategyVersion.Status.ACTIVE)


@pytest.fixture
def active_objective(strategy):
    return Objective.objects.create(
        code="O1",
        strategy_version=strategy,
        name="Mental Trainer commercial readiness",
        business_outcome="Prepare beta launch.",
        status=Objective.Status.ACTIVE,
    )


def test_objective_health_reports_blocked_and_unknown_objectives(client, strategy, active_objective):
    unknown = Objective.objects.create(
        code="O2",
        strategy_version=strategy,
        name="Executive assistant reliability",
        business_outcome="Weekly prep is reliable.",
        status=Objective.Status.ACTIVE,
    )
    Task.objects.create(
        objective=active_objective,
        title="Prepare beta checklist",
        business_outcome="Launch readiness is visible.",
        status=Task.Status.BLOCKED,
        created_by="test",
    )

    response = client.get("/api/v1/cos/objectives/health/")

    assert response.status_code == 200
    objectives = response.json()["objectives"]
    by_code = {item["objective"]["code"]: item for item in objectives}
    assert by_code["O1"]["health_status"] == "BLOCKED"
    assert by_code["O1"]["counts"]["blocked_tasks"] == 1
    assert by_code["O2"]["objective"]["id"] == str(unknown.id)
    assert by_code["O2"]["health_status"] == "UNKNOWN"


def test_objective_operating_review_includes_recommendation(client, active_objective):
    Task.objects.create(
        objective=active_objective,
        title="Verify launch page",
        business_outcome="Launch page can be accepted.",
        status=Task.Status.DELIVERED_UNVERIFIED,
        created_by="test",
    )

    response = client.get(f"/api/v1/cos/objectives/{active_objective.id}/operating-review/")

    assert response.status_code == 200
    review = response.json()["operating_review"]
    assert review["objective"]["code"] == "O1"
    assert review["health"]["health_status"] == "AT_RISK"
    assert review["recommendations"][0]["key"] == "verify-deliveries"


def test_operating_dashboard_groups_objectives_and_critical_path(client, active_objective):
    Task.objects.create(
        objective=active_objective,
        title="Blocked launch dependency",
        business_outcome="Dependency is resolved.",
        status=Task.Status.BLOCKED,
        created_by="test",
    )

    response = client.get("/api/v1/cos/operating-dashboard/?format=json")

    assert response.status_code == 200
    dashboard = response.json()["operating_dashboard"]
    assert dashboard["no_external_action"] is True
    assert dashboard["status_counts"]["BLOCKED"] == 1
    assert dashboard["objectives"][0]["objective"]["code"] == "O1"
    assert dashboard["objectives"][0]["health"]["health_status"] == "BLOCKED"
    assert dashboard["objectives"][0]["recommendations"][0]["key"] == "resolve-blockers"
    assert dashboard["critical_path"][0]["task"]["title"] == "Blocked launch dependency"


def test_next_actions_propose_creates_internal_draft_task_idempotently(client, active_objective):
    Task.objects.create(
        objective=active_objective,
        title="Blocked launch dependency",
        business_outcome="Dependency is resolved.",
        status=Task.Status.BLOCKED,
        created_by="test",
    )
    url = f"/api/v1/cos/objectives/{active_objective.id}/next-actions/propose/"
    payload = {"limit": 1}

    first = client.post(url, data=json.dumps(payload), content_type="application/json", headers=headers())
    second = client.post(url, data=json.dumps(payload), content_type="application/json", headers=headers())

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()
    body = first.json()
    assert body["no_external_action"] is True
    assert body["tasks"][0]["title"] == "Resolve blockers for O1"
    assert Task.objects.filter(objective=active_objective, title="Resolve blockers for O1", status=Task.Status.DRAFT).count() == 1
    assert AuditEvent.objects.filter(action="cos.objective.work_proposed", correlation_id="corr-cos-next-1").count() == 1
