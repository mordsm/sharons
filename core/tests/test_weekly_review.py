import pytest
from django.utils import timezone

from governance.models import ApprovalRequest
from operations.models import Task
from portfolio.models import Objective, StrategyVersion


@pytest.fixture
def dashboard_user(django_user_model):
    return django_user_model.objects.create_user(username="ceo", password="secret")


@pytest.fixture
def strategy():
    return StrategyVersion.objects.create(version=1, title="90 day plan", content={}, status=StrategyVersion.Status.ACTIVE)


@pytest.fixture
def objective(strategy):
    return Objective.objects.create(
        code="O1",
        strategy_version=strategy,
        name="Mental Trainer readiness",
        business_outcome="Commercial readiness",
        status=Objective.Status.ACTIVE,
    )


@pytest.fixture
def review_data(objective):
    blocked = Task.objects.create(
        objective=objective,
        title="Resolve payment blocker",
        status=Task.Status.BLOCKED,
        created_by="chief_of_staff",
    )
    Task.objects.create(
        objective=objective,
        title="Verify onboarding release",
        status=Task.Status.DELIVERED_UNVERIFIED,
        created_by="chief_of_staff",
    )
    Task.objects.create(
        objective=objective,
        title="Complete copy audit",
        status=Task.Status.COMPLETED,
        created_by="chief_of_staff",
    )
    ApprovalRequest.objects.create(
        subject_type="operations.Task",
        subject_id=str(blocked.id),
        subject_version=1,
        action="operations.task.transition",
        action_payload={"to_status": "APPROVED"},
        action_payload_hash="hash",
        requested_by="chief_of_staff",
        expires_at=timezone.now() + timezone.timedelta(days=1),
    )


@pytest.mark.django_db
def test_weekly_review_page_requires_login(client):
    response = client.get("/review/weekly/")

    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


@pytest.mark.django_db
def test_weekly_review_page_renders_operating_summary(client, dashboard_user, review_data):
    client.force_login(dashboard_user)
    response = client.get("/review/weekly/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "Weekly Review" in content
    assert "Resolve payment blocker" in content
    assert "Verify onboarding release" in content
    assert "Complete copy audit" in content
    assert "Pending approvals require CEO or delegated decision." in content
    assert "Review pending approvals." in content


@pytest.mark.django_db
def test_weekly_review_api_returns_structured_report(client, review_data):
    response = client.get("/api/v1/reports/weekly/")

    assert response.status_code == 200
    body = response.json()["weekly_review"]
    assert body["counts"]["active_objectives"] == 1
    assert body["counts"]["pending_approvals"] == 1
    assert body["counts"]["blocked_tasks"] == 1
    assert body["counts"]["unverified_deliveries"] == 1
    assert body["risks"]
    assert body["next_actions"]
