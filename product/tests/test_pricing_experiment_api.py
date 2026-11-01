import json

import pytest

from governance.models import AuditEvent
from operations.models import Task
from portfolio.models import Objective, ObjectiveProjectLink, Project, ProjectConnection, StrategyVersion
from product.models import PricingExperimentBrief, ProductSpecContract


pytestmark = pytest.mark.django_db


def headers(key: str) -> dict:
    return {"Idempotency-Key": key, "X-Correlation-ID": f"corr-{key}", "X-Actor-ID": "product_manager"}


def brief_payload() -> dict:
    return {
        "title": "Mental Trainer monthly price",
        "hypothesis": "A lower monthly price increases trial starts.",
        "success_metric": "trial_starts",
        "currency": "ILS",
        "variants": [
            {"label": "current", "amount": "49"},
            {"label": "candidate", "amount": "39.00"},
        ],
        "success_criterion": "Candidate trial starts are at least 15 percent higher after 14 days.",
        "stop_condition": "Stop if payment failures rise.",
    }


@pytest.fixture
def spec_contract():
    strategy = StrategyVersion.objects.create(version=1, title="90 day plan", content={}, status=StrategyVersion.Status.ACTIVE)
    objective = Objective.objects.create(
        code="O1",
        strategy_version=strategy,
        name="Mental Trainer commercial readiness",
        business_outcome="Prepare product for beta.",
        status=Objective.Status.ACTIVE,
    )
    task = Task.objects.create(
        objective=objective,
        title="Define pricing brief",
        status=Task.Status.APPROVED,
        business_outcome="Compare two monthly prices.",
        created_by="chief_of_staff",
    )
    project = Project.objects.create(name="Mental Trainer", status=Project.Status.ACTIVE, repository_reference="external://mental-trainer")
    connection = ProjectConnection.objects.create(
        project=project,
        connection_type=ProjectConnection.ConnectionType.REPOSITORY,
        adapter_type="product_manager_read_only",
        permission_mode=ProjectConnection.PermissionMode.READ_ONLY,
        capabilities={"spec_contracts": True},
    )
    ObjectiveProjectLink.objects.create(objective=objective, project=project, role=ObjectiveProjectLink.Role.PRIMARY, active=True)
    return ProductSpecContract.objects.create(
        task=task,
        project=project,
        project_connection=connection,
        title="Pricing PRD",
        objective="Compare monthly prices.",
        problem_statement="The launch price is still an assumption.",
        created_by="product_manager",
    )


def test_pricing_experiment_brief_stays_internal_until_review(client, spec_contract):
    url = f"/api/v1/product/spec-contracts/{spec_contract.id}/pricing-experiments/create/"
    payload = brief_payload()

    first = client.post(url, data=json.dumps(payload), content_type="application/json", headers=headers("price-1"))
    second = client.post(url, data=json.dumps(payload), content_type="application/json", headers=headers("price-1"))

    assert first.status_code == 201
    assert second.json() == first.json()
    body = first.json()["pricing_experiment"]
    assert body["currency"] == "ILS"
    assert body["variants"] == [
        {"label": "current", "amount": "49.00"},
        {"label": "candidate", "amount": "39.00"},
    ]
    assert body["review_status"] == PricingExperimentBrief.ReviewStatus.NEEDS_REVIEW
    assert body["no_customer_contact"] is True
    assert body["no_external_write"] is True
    assert body["no_payment"] is True
    assert body["no_spend"] is True
    assert first.json()["no_payment"] is True
    brief = PricingExperimentBrief.objects.get()
    assert AuditEvent.objects.filter(action="product.pricing_experiment.created", object_id=str(brief.id)).exists()

    reviewed = client.post(
        f"/api/v1/product/pricing-experiments/{body['id']}/review/",
        data=json.dumps({"decision": "APPROVED"}),
        content_type="application/json",
        headers=headers("price-2"),
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["pricing_experiment"]["review_status"] == PricingExperimentBrief.ReviewStatus.APPROVED
    assert reviewed.json()["no_spend"] is True
    assert AuditEvent.objects.filter(action="product.pricing_experiment.reviewed").exists()

    again = client.post(
        f"/api/v1/product/pricing-experiments/{body['id']}/review/",
        data=json.dumps({"decision": "REJECTED"}),
        content_type="application/json",
        headers=headers("price-3"),
    )
    assert again.status_code == 409
    brief.refresh_from_db()
    assert brief.review_status == PricingExperimentBrief.ReviewStatus.APPROVED


def test_pricing_experiment_rejects_payment_contact_and_non_ils(client, spec_contract):
    url = f"/api/v1/product/spec-contracts/{spec_contract.id}/pricing-experiments/create/"

    charged = brief_payload()
    charged["charge"] = {"amount": "49.00"}
    blocked = client.post(url, data=json.dumps(charged), content_type="application/json", headers=headers("price-charge"))
    assert blocked.status_code == 409
    assert PricingExperimentBrief.objects.count() == 0

    contacted = brief_payload()
    contacted["customer_email"] = "buyer@example.com"
    blocked_contact = client.post(url, data=json.dumps(contacted), content_type="application/json", headers=headers("price-contact"))
    assert blocked_contact.status_code == 409

    foreign = brief_payload()
    foreign["currency"] = "USD"
    rejected = client.post(url, data=json.dumps(foreign), content_type="application/json", headers=headers("price-usd"))
    assert rejected.status_code == 400

    single = brief_payload()
    single["variants"] = [{"label": "only", "amount": "49.00"}]
    too_few = client.post(url, data=json.dumps(single), content_type="application/json", headers=headers("price-one"))
    assert too_few.status_code == 400
    assert PricingExperimentBrief.objects.count() == 0
