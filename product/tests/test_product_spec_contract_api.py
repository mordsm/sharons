import json

import pytest

from governance.models import AuditEvent
from operations.models import Task
from portfolio.models import Objective, Project, ProjectConnection, StrategyVersion
from product.models import ProductSpecContract, ProductSpecDraft


pytestmark = pytest.mark.django_db


def headers(key: str = "product-contract-1") -> dict:
    return {"Idempotency-Key": key, "X-Correlation-ID": f"corr-{key}", "X-Actor-ID": "chief_of_staff"}


@pytest.fixture
def active_objective():
    strategy = StrategyVersion.objects.create(version=1, title="90 day plan", content={}, status=StrategyVersion.Status.ACTIVE)
    return Objective.objects.create(
        code="O1",
        strategy_version=strategy,
        name="Mental Trainer commercial readiness",
        business_outcome="Prepare product for beta.",
        status=Objective.Status.ACTIVE,
    )


@pytest.fixture
def approved_task(active_objective):
    return Task.objects.create(
        objective=active_objective,
        title="Define onboarding PRD",
        status=Task.Status.APPROVED,
        business_outcome="Clear onboarding requirements.",
        created_by="chief_of_staff",
    )


@pytest.fixture
def project_connection():
    project = Project.objects.create(
        name="Mental Trainer",
        status=Project.Status.ACTIVE,
        repository_reference="external://mental-trainer",
    )
    connection = ProjectConnection.objects.create(
        project=project,
        connection_type=ProjectConnection.ConnectionType.REPOSITORY,
        adapter_type="product_manager_read_only",
        permission_mode=ProjectConnection.PermissionMode.READ_ONLY,
        capabilities={"spec_contracts": True, "status": True},
    )
    return project, connection


def contract_payload(task: Task, project: Project, connection: ProjectConnection) -> dict:
    return {
        "task_id": str(task.id),
        "project_id": str(project.id),
        "project_connection_id": connection.id,
        "title": "Onboarding PRD",
        "spec_type": ProductSpecContract.SpecType.PRD,
        "objective": "Define the onboarding experience needed for beta readiness.",
        "target_users": ["new beta user"],
        "problem_statement": "New users need a low-friction path from install to first useful session.",
        "success_metrics": ["activation_rate", "first_session_completion"],
        "requirements": [{"id": "REQ-1", "text": "Capture first-session goal before training starts."}],
        "constraints": {"external_write": False},
        "open_questions": ["Which onboarding step has the highest drop-off risk?"],
        "deliverables": ["PRD", "acceptance criteria"],
    }


def test_product_spec_contract_create_is_idempotent_and_audited(client, approved_task, project_connection):
    project, connection = project_connection
    payload = contract_payload(approved_task, project, connection)

    first = client.post("/api/v1/product/spec-contracts/create/", data=json.dumps(payload), content_type="application/json", headers=headers())
    second = client.post("/api/v1/product/spec-contracts/create/", data=json.dumps(payload), content_type="application/json", headers=headers())

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()
    contract = ProductSpecContract.objects.get()
    assert contract.status == ProductSpecContract.Status.READY
    assert contract.no_external_write is True
    assert contract.project_connection == connection
    assert AuditEvent.objects.filter(
        action="product.spec_contract.created",
        object_id=str(contract.id),
        correlation_id="corr-product-contract-1",
    ).exists()


def test_product_spec_contract_requires_approved_or_active_task(client, active_objective, project_connection):
    project, connection = project_connection
    task = Task.objects.create(objective=active_objective, title="Draft task", status=Task.Status.DRAFT, created_by="chief")
    payload = contract_payload(task, project, connection)

    response = client.post("/api/v1/product/spec-contracts/create/", data=json.dumps(payload), content_type="application/json", headers=headers("product-contract-2"))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PRODUCT_CONTRACT_BLOCKED"
    assert ProductSpecContract.objects.count() == 0


def test_product_spec_contract_requires_read_only_connection(client, approved_task):
    project = Project.objects.create(name="Mental Trainer", status=Project.Status.ACTIVE)
    connection = ProjectConnection.objects.create(
        project=project,
        connection_type=ProjectConnection.ConnectionType.REPOSITORY,
        adapter_type="product_manager_write",
        permission_mode=ProjectConnection.PermissionMode.WRITE_APPROVED,
        capabilities={"spec_contracts": True},
    )
    payload = contract_payload(approved_task, project, connection)

    response = client.post("/api/v1/product/spec-contracts/create/", data=json.dumps(payload), content_type="application/json", headers=headers("product-contract-3"))

    assert response.status_code == 404
    assert ProductSpecContract.objects.count() == 0


def test_product_spec_contract_rejects_reused_idempotency_key_with_different_payload(client, approved_task, project_connection):
    project, connection = project_connection
    payload = contract_payload(approved_task, project, connection)
    client.post("/api/v1/product/spec-contracts/create/", data=json.dumps(payload), content_type="application/json", headers=headers("product-contract-4"))
    changed = {**payload, "title": "Changed title"}

    response = client.post("/api/v1/product/spec-contracts/create/", data=json.dumps(changed), content_type="application/json", headers=headers("product-contract-4"))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert ProductSpecContract.objects.count() == 1


def test_product_manager_status_is_read_only(client, active_objective, project_connection):
    project, _connection = project_connection
    ProductSpecContract.objects.create(
        task=Task.objects.create(
            objective=active_objective,
            title="Placeholder",
            status=Task.Status.APPROVED,
            business_outcome="Placeholder",
            created_by="chief",
        ),
        project=project,
        project_connection=_connection,
        title="Existing PRD",
        objective="Clarify scope.",
        problem_statement="Unclear scope.",
        created_by="chief",
    )

    response = client.get(f"/api/v1/product/manager/status/?project_id={project.id}")

    assert response.status_code == 200
    status = response.json()["status"]
    assert status["agent_id"] == "product_manager"
    assert status["external_write_enabled"] is False
    assert status["external_status_checked"] is False
    assert status["projects"][0]["product_spec_contracts"] == 1
    assert status["projects"][0]["product_spec_drafts"] == 0


@pytest.fixture
def product_contract(approved_task, project_connection):
    project, connection = project_connection
    return ProductSpecContract.objects.create(
        task=approved_task,
        project=project,
        project_connection=connection,
        title="Onboarding PRD",
        spec_type=ProductSpecContract.SpecType.PRD,
        objective="Define onboarding.",
        target_users=["new beta user"],
        problem_statement="Users need first-session guidance.",
        success_metrics=["activation_rate"],
        requirements=[{"id": "REQ-1", "text": "Capture first-session goal."}],
        deliverables=["PRD"],
        created_by="chief",
    )


def test_product_spec_draft_create_generates_review_artifact_and_audit(client, product_contract):
    payload = {
        "assumptions": ["Activation can be measured locally."],
        "risks": ["Onboarding may become too long."],
    }

    response = client.post(
        f"/api/v1/product/spec-contracts/{product_contract.id}/drafts/create/",
        data=json.dumps(payload),
        content_type="application/json",
        headers=headers("product-draft-1"),
    )

    assert response.status_code == 201
    body = response.json()["product_spec_draft"]
    assert body["review_status"] == ProductSpecDraft.ReviewStatus.NEEDS_REVIEW
    assert body["no_external_write"] is True
    assert body["content"]["objective"] == "Define onboarding."
    assert body["content"]["requirements"] == [{"id": "REQ-1", "text": "Capture first-session goal."}]
    draft = ProductSpecDraft.objects.get()
    product_contract.refresh_from_db()
    assert product_contract.status == ProductSpecContract.Status.IN_PROGRESS
    assert AuditEvent.objects.filter(
        action="product.spec_draft.created",
        object_id=str(draft.id),
        correlation_id="corr-product-draft-1",
    ).exists()


def test_product_spec_draft_create_is_idempotent(client, product_contract):
    payload = {"title": "Custom PRD draft", "content": {"summary": "Draft content."}}
    url = f"/api/v1/product/spec-contracts/{product_contract.id}/drafts/create/"

    first = client.post(url, data=json.dumps(payload), content_type="application/json", headers=headers("product-draft-2"))
    second = client.post(url, data=json.dumps(payload), content_type="application/json", headers=headers("product-draft-2"))

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()
    assert ProductSpecDraft.objects.count() == 1


def test_product_spec_draft_rejects_completed_contract(client, product_contract):
    product_contract.status = ProductSpecContract.Status.COMPLETED
    product_contract.save(update_fields=["status"])

    response = client.post(
        f"/api/v1/product/spec-contracts/{product_contract.id}/drafts/create/",
        data=json.dumps({}),
        content_type="application/json",
        headers=headers("product-draft-3"),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PRODUCT_CONTRACT_BLOCKED"
    assert ProductSpecDraft.objects.count() == 0


def test_product_status_counts_drafts(client, product_contract):
    ProductSpecDraft.objects.create(
        contract=product_contract,
        title="Existing draft",
        content={"summary": "Existing"},
        created_by="chief",
    )

    response = client.get(f"/api/v1/product/manager/status/?project_id={product_contract.project_id}")

    assert response.status_code == 200
    status = response.json()["status"]
    assert status["projects"][0]["product_spec_contracts"] == 1
    assert status["projects"][0]["product_spec_drafts"] == 1


@pytest.fixture
def product_draft(product_contract):
    return ProductSpecDraft.objects.create(
        contract=product_contract,
        title="Onboarding PRD Draft",
        content={"summary": "Draft"},
        created_by="product_manager",
    )


def test_product_spec_draft_review_approves_and_completes_contract(client, product_draft):
    response = client.post(
        f"/api/v1/product/spec-drafts/{product_draft.id}/review/",
        data=json.dumps({"decision": ProductSpecDraft.ReviewStatus.APPROVED, "reviewer_notes": "Ready for implementation planning."}),
        content_type="application/json",
        headers=headers("product-draft-review-1"),
    )

    assert response.status_code == 200
    body = response.json()["product_spec_draft"]
    assert body["review_status"] == ProductSpecDraft.ReviewStatus.APPROVED
    assert body["content"]["review"]["reviewer_notes"] == "Ready for implementation planning."
    product_draft.refresh_from_db()
    product_draft.contract.refresh_from_db()
    assert product_draft.contract.status == ProductSpecContract.Status.COMPLETED
    assert AuditEvent.objects.filter(
        action="product.spec_draft.reviewed",
        object_id=str(product_draft.id),
        correlation_id="corr-product-draft-review-1",
        metadata__decision=ProductSpecDraft.ReviewStatus.APPROVED,
    ).exists()


def test_product_spec_draft_review_rejects_and_keeps_contract_in_progress(client, product_draft):
    product_draft.contract.status = ProductSpecContract.Status.IN_PROGRESS
    product_draft.contract.save(update_fields=["status"])

    response = client.post(
        f"/api/v1/product/spec-drafts/{product_draft.id}/review/",
        data=json.dumps({"decision": ProductSpecDraft.ReviewStatus.REJECTED, "reviewer_notes": "Missing activation metric definition."}),
        content_type="application/json",
        headers=headers("product-draft-review-2"),
    )

    assert response.status_code == 200
    product_draft.refresh_from_db()
    product_draft.contract.refresh_from_db()
    assert product_draft.review_status == ProductSpecDraft.ReviewStatus.REJECTED
    assert product_draft.contract.status == ProductSpecContract.Status.IN_PROGRESS


def test_product_spec_draft_review_is_idempotent(client, product_draft):
    payload = {"decision": ProductSpecDraft.ReviewStatus.APPROVED}
    url = f"/api/v1/product/spec-drafts/{product_draft.id}/review/"

    first = client.post(url, data=json.dumps(payload), content_type="application/json", headers=headers("product-draft-review-3"))
    second = client.post(url, data=json.dumps(payload), content_type="application/json", headers=headers("product-draft-review-3"))

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert ProductSpecDraft.objects.count() == 1


def test_product_spec_draft_review_rejects_already_reviewed_draft(client, product_draft):
    product_draft.review_status = ProductSpecDraft.ReviewStatus.APPROVED
    product_draft.save(update_fields=["review_status"])

    response = client.post(
        f"/api/v1/product/spec-drafts/{product_draft.id}/review/",
        data=json.dumps({"decision": ProductSpecDraft.ReviewStatus.REJECTED}),
        content_type="application/json",
        headers=headers("product-draft-review-4"),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PRODUCT_CONTRACT_BLOCKED"


def test_product_spec_draft_tasks_propose_creates_internal_tasks_idempotently(client, product_draft):
    product_draft.review_status = ProductSpecDraft.ReviewStatus.APPROVED
    product_draft.content = {
        "requirements": [
            {"id": "REQ-1", "text": "Capture first-session goal."},
            {"id": "REQ-2", "text": "Show first recommended exercise."},
        ],
        "acceptance_focus": ["Success metric is traceable to product spec."],
    }
    product_draft.save(update_fields=["review_status", "content"])
    url = f"/api/v1/product/spec-drafts/{product_draft.id}/tasks/propose/"
    payload = {"limit": 2}

    first = client.post(url, data=json.dumps(payload), content_type="application/json", headers=headers("product-tasks-1"))
    second = client.post(url, data=json.dumps(payload), content_type="application/json", headers=headers("product-tasks-1"))

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()
    body = first.json()
    assert body["no_external_write"] is True
    assert len(body["tasks"]) == 2
    assert Task.objects.filter(external_key=f"product-spec:{product_draft.id}:REQ-1", status=Task.Status.DRAFT).exists()
    assert AuditEvent.objects.filter(
        action="product.spec_draft.tasks_proposed",
        object_id=str(product_draft.id),
        correlation_id="corr-product-tasks-1",
        metadata__task_count=2,
        metadata__no_external_write=True,
    ).count() == 1


def test_product_spec_draft_tasks_propose_requires_approved_draft(client, product_draft):
    response = client.post(
        f"/api/v1/product/spec-drafts/{product_draft.id}/tasks/propose/",
        data=json.dumps({"limit": 1}),
        content_type="application/json",
        headers=headers("product-tasks-2"),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PRODUCT_CONTRACT_BLOCKED"


def test_product_project_readiness_reports_ready_for_approved_closed_spec(client, product_draft):
    product_draft.review_status = ProductSpecDraft.ReviewStatus.APPROVED
    product_draft.contract.status = ProductSpecContract.Status.COMPLETED
    product_draft.contract.open_questions = []
    product_draft.contract.save(update_fields=["status", "open_questions"])
    product_draft.save(update_fields=["review_status"])

    response = client.get(f"/api/v1/product/projects/{product_draft.contract.project_id}/readiness/")

    assert response.status_code == 200
    readiness = response.json()["readiness"]
    assert readiness["readiness_status"] == "READY_FOR_IMPLEMENTATION"
    assert readiness["counts"]["approved_drafts"] == 1
    assert readiness["external_write_enabled"] is False


def test_product_project_readiness_reports_blockers(client, project_connection):
    project, _connection = project_connection

    response = client.get(f"/api/v1/product/projects/{project.id}/readiness/")

    assert response.status_code == 200
    readiness = response.json()["readiness"]
    assert readiness["readiness_status"] == "BLOCKED"
    assert "No product spec contracts exist for this project." in readiness["blockers"]


def test_product_project_roadmap_returns_internal_milestones(client, product_draft):
    product_draft.review_status = ProductSpecDraft.ReviewStatus.APPROVED
    product_draft.contract.open_questions = []
    product_draft.contract.save(update_fields=["open_questions"])
    product_draft.save(update_fields=["review_status"])

    response = client.get(f"/api/v1/product/projects/{product_draft.contract.project_id}/roadmap/")

    assert response.status_code == 200
    roadmap = response.json()["roadmap"]
    assert roadmap["external_write_enabled"] is False
    assert roadmap["project"]["id"] == str(product_draft.contract.project_id)
    assert roadmap["milestones"][0]["title"] == "Onboarding PRD"
    assert roadmap["milestones"][0]["status"] == "READY_FOR_IMPLEMENTATION"
    assert roadmap["milestones"][0]["objective_code"] == "O1"
    assert roadmap["milestones"][0]["success_metrics"] == ["activation_rate"]
    assert roadmap["open_questions"] == []


def test_product_feature_prioritization_scores_requirements_read_only(client, product_contract):
    product_contract.requirements = [
        {
            "id": "REQ-HIGH",
            "text": "Show first recommended exercise.",
            "impact": 5,
            "urgency": 4,
            "strategic_fit": 5,
            "confidence": 4,
            "effort": 2,
            "risk": 2,
        },
        {
            "id": "REQ-LOW",
            "text": "Add optional welcome animation.",
            "impact": 2,
            "urgency": 1,
            "strategic_fit": 2,
            "confidence": 3,
            "effort": 4,
            "risk": 3,
        },
    ]
    product_contract.save(update_fields=["requirements"])

    response = client.get(
        "/api/v1/product/features/prioritization/",
        {"project_id": str(product_contract.project_id)},
    )

    assert response.status_code == 200
    prioritization = response.json()["prioritization"]
    assert prioritization["external_write_enabled"] is False
    assert prioritization["formula"] == "(impact * urgency * strategic_fit * confidence) / (effort * risk)"
    assert [feature["feature_id"] for feature in prioritization["features"]] == ["REQ-HIGH", "REQ-LOW"]
    assert prioritization["features"][0]["priority_score"] == 100.0
    assert prioritization["features"][0]["no_external_write"] is True
