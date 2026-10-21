import json
from datetime import date, timedelta
import pytest
from django.utils import timezone
from django.contrib.auth import get_user_model

from portfolio.models import Project, Objective, StrategyVersion
from product.pm_engine import (
    PrdAndUserStoryEngine,
    RicePrioritizationEngine,
    RoadmapAndMilestoneEngine,
    DiscoveryAndFeedbackEngine,
)
from product.models import (
    ProductFeature,
    ProductFeedback,
    ProductMilestone,
    ProductSpecContract,
    ProductSpecDraft,
)

pytestmark = pytest.mark.django_db


def headers(key: str = "pm-test-1") -> dict:
    return {
        "HTTP_IDEMPOTENCY_KEY": key,
        "HTTP_X_CORRELATION_ID": f"corr-{key}",
        "HTTP_X_ACTOR_ID": "product_manager",
    }


@pytest.fixture
def test_user():
    user_model = get_user_model()
    return user_model.objects.create_user(username="pm_tester", password="password123")


@pytest.fixture
def strategy():
    return StrategyVersion.objects.create(
        version=1,
        title="Q4 Product Strategy",
        content={},
        status=StrategyVersion.Status.ACTIVE,
    )


@pytest.fixture
def active_objective(strategy):
    return Objective.objects.create(
        code="OBJ-PM-TEST",
        strategy_version=strategy,
        name="Launch Self-Serve Billing Portal",
        business_outcome="Reduce onboarding friction by 80%",
        status=Objective.Status.ACTIVE,
        owner_agent_id="product_manager",
    )


@pytest.fixture
def active_project():
    return Project.objects.create(
        slug="portal-app",
        name="Customer Self-Serve Portal",
        owner="pm",
        status=Project.Status.ACTIVE,
    )


# ==============================================================================
# 1. PRD & User Story Engine Tests
# ==============================================================================

def test_prd_generation_and_user_story_decomposition(active_project, active_objective):
    result = PrdAndUserStoryEngine.generate_prd_and_stories(
        project_id=active_project.id,
        title="Enterprise Single Sign-On (SSO)",
        problem_statement="Enterprise customers cannot onboard without SAML2/Okta integration.",
        target_persona="IT Security Administrator",
        requirements=["SAML 2.0 Web Browser SSO profile", "Just-In-Time (JIT) user provisioning"],
    )

    assert result["contract_id"] is not None
    assert result["draft_id"] is not None
    assert len(result["acceptance_criteria"]) >= 3
    assert len(result["features_created"]) == 3

    contract = ProductSpecContract.objects.get(id=result["contract_id"])
    assert contract.spec_type == ProductSpecContract.SpecType.PRD
    assert contract.status == ProductSpecContract.Status.READY

    draft = ProductSpecDraft.objects.get(id=result["draft_id"])
    assert draft.review_status == ProductSpecDraft.ReviewStatus.NEEDS_REVIEW
    assert "user_stories" in draft.content

    features = ProductFeature.objects.filter(project=active_project)
    assert features.count() == 3
    for f in features:
        assert f.rice_score > 0
        assert len(f.acceptance_criteria) >= 2


# ==============================================================================
# 2. RICE Prioritization Engine Tests
# ==============================================================================

def test_rice_prioritization_engine(active_project):
    # Feature 1: High Reach, High Impact -> High RICE
    f_high = ProductFeature.objects.create(
        project=active_project,
        title="One-Click Checkout",
        reach=5000,
        impact=3.0,
        confidence=0.8,
        effort=2.0,
    )
    # Feature 2: Low Reach, High Effort -> Low RICE
    f_low = ProductFeature.objects.create(
        project=active_project,
        title="Custom Export to CSV v2",
        reach=200,
        impact=0.5,
        confidence=0.5,
        effort=5.0,
    )

    ranked = RicePrioritizationEngine.rank_backlog(project_id=active_project.id)
    assert len(ranked) >= 2

    top = ranked[0]
    assert top["id"] == str(f_high.id)
    assert top["priority_tier"] == "P0_CRITICAL"
    assert top["rice_score"] == 6000.0

    bottom = ranked[-1]
    assert bottom["id"] == str(f_low.id)
    assert bottom["priority_tier"] == "P3_LOW"
    assert bottom["rice_score"] == 10.0

    # Test update_rice
    updated = RicePrioritizationEngine.update_rice(
        feature_id=f_low.id,
        reach=1000,
        effort=1.0,
    )
    assert updated["reach"] == 1000
    assert updated["effort"] == 1.0
    f_low.refresh_from_db()
    assert f_low.rice_score == 250.0  # (1000 * 0.5 * 0.5) / 1.0 = 250


# ==============================================================================
# 3. Roadmap & Milestone Engine Tests
# ==============================================================================

def test_roadmap_milestones_and_health(active_project):
    target = date.today() + timedelta(days=14)
    m = RoadmapAndMilestoneEngine.create_milestone(
        project_id=active_project.id,
        name="MVP Beta Release",
        target_date=target,
        description="First external pilot with 5 enterprises",
    )

    # Attach two features
    f1 = ProductFeature.objects.create(
        project=active_project,
        milestone=m,
        title="Auth Module",
        status=ProductFeature.Status.COMPLETED,
    )
    f2 = ProductFeature.objects.create(
        project=active_project,
        milestone=m,
        title="Billing Webhook",
        status=ProductFeature.Status.IN_PROGRESS,
    )

    roadmap = RoadmapAndMilestoneEngine.get_roadmap(project_id=active_project.id)
    assert len(roadmap) == 1
    item = roadmap[0]
    assert item["name"] == "MVP Beta Release"
    assert item["features_total"] == 2
    assert item["features_completed"] == 1
    assert item["progress_percentage"] == 50.0
    assert item["health"] == "ON_TRACK"

    # Complete f2
    f2.status = ProductFeature.Status.COMPLETED
    f2.save()

    roadmap_completed = RoadmapAndMilestoneEngine.get_roadmap(project_id=active_project.id)
    assert roadmap_completed[0]["progress_percentage"] == 100.0
    assert roadmap_completed[0]["health"] == "COMPLETED"


# ==============================================================================
# 4. Customer Discovery & Feedback Tests
# ==============================================================================

def test_customer_discovery_feedback(active_project):
    f = ProductFeature.objects.create(project=active_project, title="Invoice PDF Download")
    
    fb1 = DiscoveryAndFeedbackEngine.ingest_feedback(
        project_id=active_project.id,
        source="Customer Interview #12",
        content="The PDF invoices are missing our European VAT number.",
        user_segment="Enterprise EU",
        sentiment=ProductFeedback.Sentiment.NEGATIVE,
        action_item="Add VAT field to invoice template",
        feature_id=f.id,
    )
    fb2 = DiscoveryAndFeedbackEngine.ingest_feedback(
        project_id=active_project.id,
        source="G2 Review",
        content="Love the speed and simplicity of the new dashboard!",
        sentiment=ProductFeedback.Sentiment.POSITIVE,
    )

    summary = DiscoveryAndFeedbackEngine.get_feedback_summary(project_id=active_project.id)
    assert summary["total_feedback_count"] >= 2
    assert summary["sentiment_distribution"]["positive"] >= 1
    assert summary["sentiment_distribution"]["negative"] >= 1


# ==============================================================================
# 5. Full REST API & UI Integration Tests
# ==============================================================================

def test_api_prd_generate(client, active_project, active_objective):
    res = client.post(
        "/api/v1/product/prd/generate/",
        data=json.dumps({
            "project_id": str(active_project.id),
            "title": "Automated Tax Calculation",
            "problem_statement": "Manual tax compliance causes delays in international invoicing.",
            "target_persona": "Head of Finance",
        }),
        content_type="application/json",
        **headers("prd-gen-api-1"),
    )
    assert res.status_code == 201
    data = res.json()
    assert "prd" in data
    assert "contract_id" in data["prd"]
    assert len(data["prd"]["features_created"]) == 3


def test_api_features_rank_and_rice_update(client, active_project):
    feat = ProductFeature.objects.create(
        project=active_project,
        title="Webhooks v2",
        reach=1000,
        impact=2.0,
        confidence=0.8,
        effort=2.0,
    )

    # 1. GET rank
    res_rank = client.get(f"/api/v1/product/features/rank/?project_id={active_project.id}")
    assert res_rank.status_code == 200
    assert res_rank.json()["total_features"] >= 1

    # 2. POST update RICE
    res_upd = client.post(
        f"/api/v1/product/features/{feat.id}/rice/",
        data=json.dumps({"effort": 1.0}),
        content_type="application/json",
        **headers("rice-up-api-1"),
    )
    assert res_upd.status_code == 200
    assert res_upd.json()["feature"]["rice_score"] == 1600.0  # (1000*2*0.8)/1.0


def test_api_milestones_and_roadmap(client, active_project):
    res_m = client.post(
        "/api/v1/product/milestones/create/",
        data=json.dumps({
            "project_id": str(active_project.id),
            "name": "General Availability (GA)",
            "target_date": (date.today() + timedelta(days=30)).isoformat(),
            "description": "Public launch",
        }),
        content_type="application/json",
    )
    assert res_m.status_code == 201

    res_rm = client.get(f"/api/v1/product/roadmap/timeline/?project_id={active_project.id}")
    assert res_rm.status_code == 200
    assert res_rm.json()["total_milestones"] >= 1


def test_api_feedback_and_dashboard_page(client, test_user, active_project):
    # 1. POST feedback
    res_fb = client.post(
        "/api/v1/product/feedback/ingest/",
        data=json.dumps({
            "project_id": str(active_project.id),
            "source": "Zendesk Ticket #104",
            "content": "Need webhooks to retry with exponential backoff.",
            "sentiment": "NEUTRAL",
            "action_item": "Implement retry policy",
        }),
        content_type="application/json",
    )
    assert res_fb.status_code == 201

    # 2. GET feedback summary
    res_sum = client.get(f"/api/v1/product/feedback/summary/?project_id={active_project.id}")
    assert res_sum.status_code == 200
    assert res_sum.json()["total_feedback_count"] >= 1

    # 3. GET HTML dashboard page
    client.force_login(test_user)
    res_page = client.get("/product/")
    assert res_page.status_code == 200
    html = res_page.content.decode("utf-8")
    assert "Product Management &amp; Roadmap" in html or "Product Management & Roadmap" in html
    assert "RICE Ranked Backlog" in html
    assert "Voice of Customer &amp; Discovery Insights" in html or "Voice of Customer & Discovery Insights" in html

