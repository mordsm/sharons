import pytest
from django.core.management import call_command
from django.utils import timezone

from governance.models import AuditEvent
from portfolio.models import Objective, StrategyVersion
from portfolio.services import seed_approved_objectives


@pytest.mark.django_db
def test_objectives_list_returns_seeded_objectives(client):
    seed_approved_objectives(actor_id="test", correlation_id="corr-objectives")

    response = client.get("/api/v1/objectives/")

    assert response.status_code == 200
    objectives = response.json()["objectives"]
    assert [objective["code"] for objective in objectives] == ["O1", "O2", "O3", "O4"]
    assert all(objective["status"] == Objective.Status.ACTIVE for objective in objectives)


@pytest.mark.django_db
def test_seed_objectives_is_idempotent():
    seed_approved_objectives(actor_id="test", correlation_id="corr-seed-1")
    seed_approved_objectives(actor_id="test", correlation_id="corr-seed-2")

    assert StrategyVersion.objects.count() == 1
    assert Objective.objects.count() == 4
    assert AuditEvent.objects.filter(action="portfolio.objectives.seeded").count() == 2


@pytest.mark.django_db
def test_seed_objectives_management_command():
    call_command("seed_objectives", correlation_id="corr-command", actor_id="test")

    assert Objective.objects.count() == 4
    assert Objective.objects.get(code="O1").name == "Mental Trainer commercial readiness"


@pytest.mark.django_db
def test_objectives_list_orders_by_code(client):
    strategy = StrategyVersion.objects.create(
        version=1,
        title="Initial strategy",
        content={},
        status=StrategyVersion.Status.ACTIVE,
        valid_from=timezone.now(),
    )
    Objective.objects.create(
        code="O2",
        strategy_version=strategy,
        name="Second",
        business_outcome="Second outcome",
        status=Objective.Status.ACTIVE,
    )
    Objective.objects.create(
        code="O1",
        strategy_version=strategy,
        name="First",
        business_outcome="First outcome",
        status=Objective.Status.ACTIVE,
    )

    response = client.get("/api/v1/objectives/")

    assert response.status_code == 200
    assert [objective["code"] for objective in response.json()["objectives"]] == ["O1", "O2"]
