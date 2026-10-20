import json
from datetime import timedelta
import pytest
from django.utils import timezone
from django.contrib.auth import get_user_model

from core.cos_engine import (
    CriticalPathEngine,
    DependencyCycleError,
    RiskRegisterEngine,
    WipAndStaleControlEngine,
    CeoDecisionBundleEngine,
)
from core.services import canonical_hash
from governance.models import ApprovalRequest, AuditEvent
from operations.models import Task, TaskDependency, Evidence, AcceptanceCriterion
from portfolio.models import Objective, ObjectiveRisk, StrategyVersion

pytestmark = pytest.mark.django_db


def headers(key: str = "cos-test-1") -> dict:
    return {
        "HTTP_IDEMPOTENCY_KEY": key,
        "HTTP_X_CORRELATION_ID": f"corr-{key}",
        "HTTP_X_ACTOR_ID": "chief_of_staff",
    }


@pytest.fixture
def strategy():
    return StrategyVersion.objects.create(
        version=1,
        title="Q4 90-Day Plan",
        content={},
        status=StrategyVersion.Status.ACTIVE,
    )


@pytest.fixture
def active_objective(strategy):
    return Objective.objects.create(
        code="O1",
        strategy_version=strategy,
        name="Mental Trainer commercial readiness",
        business_outcome="Prepare desktop and mobile beta launch.",
        status=Objective.Status.ACTIVE,
    )


@pytest.fixture
def test_user():
    User = get_user_model()
    return User.objects.create_user(username="ceo", email="ceo@sharons.local", password="password123")


# ==============================================================================
# 1. Critical Path & Dependencies Tests
# ==============================================================================

def test_critical_path_cycle_detection(active_objective):
    t1 = Task.objects.create(objective=active_objective, title="Task A", created_by="test")
    t2 = Task.objects.create(objective=active_objective, title="Task B", created_by="test")
    t3 = Task.objects.create(objective=active_objective, title="Task C", created_by="test")

    # A depends on B, B depends on C
    CriticalPathEngine.add_dependency(task_id=str(t1.id), depends_on_id=str(t2.id))
    CriticalPathEngine.add_dependency(task_id=str(t2.id), depends_on_id=str(t3.id))

    # Adding C depends on A must raise DependencyCycleError
    with pytest.raises(DependencyCycleError):
        CriticalPathEngine.add_dependency(task_id=str(t3.id), depends_on_id=str(t1.id))


def test_critical_path_root_blockers_and_analysis(active_objective):
    t_root = Task.objects.create(objective=active_objective, title="Root Database Schema", status=Task.Status.IN_PROGRESS, created_by="test")
    t_mid = Task.objects.create(objective=active_objective, title="API Layer", status=Task.Status.PLANNED, created_by="test")
    t_leaf = Task.objects.create(objective=active_objective, title="Frontend UI", status=Task.Status.PLANNED, created_by="test")

    # API depends on DB; UI depends on API
    CriticalPathEngine.add_dependency(task_id=str(t_mid.id), depends_on_id=str(t_root.id))
    CriticalPathEngine.add_dependency(task_id=str(t_leaf.id), depends_on_id=str(t_mid.id))

    analysis = CriticalPathEngine.analyze_critical_path(objective_id=str(active_objective.id))

    assert analysis["has_cycle"] is False
    assert analysis["open_tasks_count"] == 3
    assert len(analysis["root_blockers"]) >= 1
    root = analysis["root_blockers"][0]
    assert root["task_id"] == str(t_root.id)
    assert root["blocking_count"] == 1
    assert "API Layer" in root["blocked_tasks"]

    # Critical path tasks check
    cp_tasks = {item["task_id"]: item for item in analysis["critical_path_tasks"]}
    assert cp_tasks[str(t_root.id)]["chain_depth"] >= 2


# ==============================================================================
# 2. WIP Limits & Stale Task Controls Tests
# ==============================================================================

def test_wip_limits_and_stale_task_controls(active_objective):
    # Create 3 active tasks
    for i in range(3):
        Task.objects.create(
            objective=active_objective,
            title=f"Active Task {i+1}",
            status=Task.Status.IN_PROGRESS,
            created_by="test",
        )

    # 4th task should flag over limit
    t4 = Task.objects.create(
        objective=active_objective,
        title="Excess Task 4",
        status=Task.Status.DRAFT,
        created_by="test",
    )

    allowed, msg = WipAndStaleControlEngine.check_wip_limit_for_task(t4)
    assert allowed is False
    assert "WIP limit reached" in msg

    wip_report = WipAndStaleControlEngine.get_wip_report()
    assert wip_report["total_wip"] == 3
    obj_entry = next(item for item in wip_report["objectives"] if item["objective_code"] == "O1")
    assert obj_entry["wip_count"] == 3
    assert obj_entry["is_over_limit"] is False

    # Stale tasks test: update updated_at back 10 days
    stale_task = Task.objects.create(
        objective=active_objective,
        title="Stuck in limbo",
        status=Task.Status.IN_PROGRESS,
        created_by="test",
    )
    ten_days_ago = timezone.now() - timedelta(days=10)
    Task.objects.filter(id=stale_task.id).update(updated_at=ten_days_ago)

    stale_list = WipAndStaleControlEngine.scan_stale_tasks(stale_days=5)
    stale_ids = [item["task_id"] for item in stale_list]
    assert str(stale_task.id) in stale_ids
    found = next(item for item in stale_list if item["task_id"] == str(stale_task.id))
    assert found["severity"] in ["HIGH", "CRITICAL"]


# ==============================================================================
# 3. Objective Risk Register Tests
# ==============================================================================

def test_objective_risk_register_lifecycle(active_objective):
    risk = RiskRegisterEngine.create_risk(
        objective_id=str(active_objective.id),
        title="App Store Review Delay",
        category=ObjectiveRisk.Category.EXTERNAL,
        severity=ObjectiveRisk.Severity.HIGH,
        likelihood=ObjectiveRisk.Severity.MEDIUM,
        description="Apple review can take 2 weeks.",
        mitigation_plan="Submit beta build early via TestFlight.",
        owner="product_manager",
        actor_id="test_cos",
    )

    assert risk.id is not None
    assert risk.severity == "HIGH"
    assert risk.status == "IDENTIFIED"

    # Verify audit event recorded
    assert AuditEvent.objects.filter(object_id=str(risk.id), action="cos.risk.created").exists()

    # Update risk
    updated = RiskRegisterEngine.update_risk(
        risk_id=str(risk.id),
        payload={"status": ObjectiveRisk.Status.MITIGATED, "severity": ObjectiveRisk.Severity.LOW},
        actor_id="test_cos",
    )
    assert updated.status == "MITIGATED"
    assert updated.severity == "LOW"

    # Risk matrix calculation
    matrix = RiskRegisterEngine.get_risk_matrix(objective_id=str(active_objective.id))
    assert matrix["total_risks"] == 1
    assert matrix["risks"][0]["title"] == "App Store Review Delay"


# ==============================================================================
# 4. Weekly CEO Decision Bundle Tests
# ==============================================================================

def test_ceo_decision_bundle_generation_and_execution(active_objective, test_user):
    # Create an approval request
    approval_payload = {"rule_name": "Invoice Auto Routing"}
    approval = ApprovalRequest.objects.create(
        subject_type="governance.Rule",
        subject_id="rule-test-1",
        subject_version=1,
        action="governance.rule.activate",
        action_payload=approval_payload,
        action_payload_hash=canonical_hash(approval_payload),
        requested_by="developer",
        status=ApprovalRequest.Status.PENDING,
        expires_at=timezone.now() + timedelta(days=2),
    )

    # Create a verified delivery
    t_done = Task.objects.create(
        objective=active_objective,
        title="Deploy Auth Middleware",
        status=Task.Status.COMPLETED,
        created_by="test",
    )
    Evidence.objects.create(
        task=t_done,
        kind=Evidence.Kind.TEST,
        uri_or_reference="tests/test_auth.py::test_pass",
        verified=True,
        created_by="qa",
    )
    AcceptanceCriterion.objects.create(
        task=t_done,
        description="Passes 100% security tests",
        status="PASSED",
    )

    bundle = CeoDecisionBundleEngine.generate_decision_bundle()

    assert bundle["agenda_duration_minutes"] == 30
    assert bundle["executive_summary"]["active_objectives_count"] >= 1
    assert bundle["executive_summary"]["pending_decisions_count"] >= 1
    assert bundle["executive_summary"]["verified_deliveries_past_week"] >= 1

    # Check decision queue item
    dec_item = next(d for d in bundle["decision_queue"] if d["approval_id"] == str(approval.id))
    assert dec_item["cos_recommendation"] == "APPROVE_CONDITIONAL"

    # Execute decision
    res = CeoDecisionBundleEngine.execute_decision(
        approval_id=str(approval.id),
        decision=ApprovalRequest.Status.APPROVED,
        reason="Reviewed and approved by CEO during weekly operating review.",
        decided_by="ceo",
    )
    assert res["decision"] == "APPROVED"
    approval.refresh_from_db()
    assert approval.status == ApprovalRequest.Status.APPROVED


# ==============================================================================
# 5. Full REST API Integration Tests
# ==============================================================================

def test_api_critical_path_and_dependency_endpoints(client, active_objective):
    t1 = Task.objects.create(objective=active_objective, title="Task X", created_by="api_test")
    t2 = Task.objects.create(objective=active_objective, title="Task Y", created_by="api_test")

    # Add dependency via POST
    dep_res = client.post(
        "/api/v1/cos/dependencies/add/",
        data=json.dumps({"task_id": str(t2.id), "depends_on_id": str(t1.id)}),
        content_type="application/json",
        **headers("dep-add-1"),
    )
    assert dep_res.status_code == 201
    assert dep_res.json()["dependency"]["task_id"] == str(t2.id)

    # Query Critical Path via GET
    cp_res = client.get(f"/api/v1/cos/critical-path/?objective_id={active_objective.id}")
    assert cp_res.status_code == 200
    assert cp_res.json()["open_tasks_count"] == 2
    assert cp_res.json()["root_blockers"][0]["task_id"] == str(t1.id)

    # Remove dependency via POST
    rem_res = client.post(
        "/api/v1/cos/dependencies/remove/",
        data=json.dumps({"task_id": str(t2.id), "depends_on_id": str(t1.id)}),
        content_type="application/json",
        **headers("dep-rem-1"),
    )
    assert rem_res.status_code == 200
    assert rem_res.json()["removed"] is True


def test_api_wip_and_stale_endpoint(client, active_objective):
    res = client.get("/api/v1/cos/wip-and-stale/")
    assert res.status_code == 200
    data = res.json()
    assert "wip_report" in data
    assert "stale_tasks" in data


def test_api_risks_lifecycle(client, active_objective):
    # 1. Create Risk
    create_res = client.post(
        "/api/v1/cos/risks/create/",
        data=json.dumps({
            "objective_id": str(active_objective.id),
            "title": "Vendor API Deprecation",
            "category": "TECHNICAL",
            "severity": "HIGH",
            "likelihood": "MEDIUM",
            "mitigation_plan": "Migrate to v2 endpoints",
        }),
        content_type="application/json",
        **headers("risk-cr-1"),
    )
    assert create_res.status_code == 201
    risk_id = create_res.json()["risk"]["id"]

    # 2. List Risks
    list_res = client.get(f"/api/v1/cos/risks/?objective_id={active_objective.id}")
    assert list_res.status_code == 200
    assert list_res.json()["total_risks"] >= 1

    # 3. Update Risk
    upd_res = client.post(
        f"/api/v1/cos/risks/{risk_id}/",
        data=json.dumps({"status": "MITIGATED"}),
        content_type="application/json",
        **headers("risk-up-1"),
    )
    assert upd_res.status_code == 200
    assert upd_res.json()["risk"]["status"] == "MITIGATED"


def test_api_decision_bundle_and_decide(client, active_objective):
    # 1. GET decision bundle
    bundle_res = client.get("/api/v1/cos/decision-bundle/")
    assert bundle_res.status_code == 200
    bundle_data = bundle_res.json()
    assert bundle_data["agenda_duration_minutes"] == 30
    assert "decision_queue" in bundle_data

    # 2. Create an approval to decide
    app_payload = {"rule_name": "Test Decide"}
    app = ApprovalRequest.objects.create(
        subject_type="governance.Rule",
        subject_id="rule-test-decide",
        subject_version=1,
        action="governance.rule.activate",
        action_payload=app_payload,
        action_payload_hash=canonical_hash(app_payload),
        requested_by="developer",
        status=ApprovalRequest.Status.PENDING,
        expires_at=timezone.now() + timedelta(days=1),
    )

    dec_res = client.post(
        "/api/v1/cos/decision-bundle/decide/",
        data=json.dumps({
            "approval_id": str(app.id),
            "decision": "APPROVED",
            "reason": "CEO confirmed in operating review",
        }),
        content_type="application/json",
        **headers("bundle-dec-1"),
    )
    assert dec_res.status_code == 200
    assert dec_res.json()["result"]["decision"] == "APPROVED"


def test_weekly_decision_bundle_page_rendered(client, test_user):
    client.force_login(test_user)
    res = client.get("/review/weekly/decision-bundle/")
    assert res.status_code == 200
    html = res.content.decode("utf-8")
    assert "CEO 30-Minute Weekly Decision Bundle" in html
    assert "CEO Decision Queue" in html
    assert "Critical Path & Root Blockers" in html
    assert "Objective Risk Register" in html
