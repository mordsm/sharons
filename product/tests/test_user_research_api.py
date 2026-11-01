import json
from datetime import date

import pytest

from governance.models import AuditEvent
from operations.models import Task
from portfolio.models import Objective, ObjectiveProjectLink, Project, ProjectConnection, StrategyVersion
from product.models import CompetitiveAnalysisDraft, ProductMilestone, ProductSpecContract, UserResearchContract, UserResearchQuestion


pytestmark = pytest.mark.django_db


def headers(key: str) -> dict:
    return {"Idempotency-Key": key, "X-Correlation-ID": f"corr-{key}", "X-Actor-ID": "product_manager"}


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
        title="Define onboarding PRD",
        status=Task.Status.APPROVED,
        business_outcome="Clear onboarding requirements.",
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
    contract = ProductSpecContract.objects.create(
        task=task,
        project=project,
        project_connection=connection,
        title="Onboarding PRD",
        objective="Define onboarding.",
        problem_statement="Users need first-session guidance.",
        created_by="product_manager",
    )
    return contract, objective, project


def test_user_research_contract_records_internal_artifacts_without_contact(client, spec_contract):
    contract, _objective, project = spec_contract
    payload = {
        "title": "Onboarding discovery notes",
        "research_question": "Where do new users hesitate before the first session?",
        "method": "INTERVIEW_NOTES",
        "participant_segment": "new beta cohort",
    }
    url = f"/api/v1/product/spec-contracts/{contract.id}/user-research/create/"

    first = client.post(url, data=json.dumps(payload), content_type="application/json", headers=headers("research-1"))
    second = client.post(url, data=json.dumps(payload), content_type="application/json", headers=headers("research-1"))

    assert first.status_code == 201
    assert second.json() == first.json()
    body = first.json()["user_research_contract"]
    assert body["spec_contract_id"] == str(contract.id)
    assert body["project_id"] == str(project.id)
    assert body["no_customer_contact"] is True
    assert body["no_external_write"] is True
    research = UserResearchContract.objects.get()
    assert AuditEvent.objects.filter(action="product.user_research.created", object_id=str(research.id)).exists()

    interview = client.post(
        f"/api/v1/product/user-research/{research.id}/interviews/create/",
        data=json.dumps({"label": "cohort session 1", "segment": "new beta cohort", "summary": "Users pause on the goal prompt.", "observations": ["Goal prompt is unclear."]}),
        content_type="application/json",
        headers=headers("research-interview-1"),
    )
    assert interview.status_code == 201
    assert interview.json()["no_customer_contact"] is True

    finding = client.post(
        f"/api/v1/product/user-research/{research.id}/findings/create/",
        data=json.dumps({
            "statement": "The goal prompt is the main hesitation point.",
            "evidence_note": "Repeated in the first internal session notes.",
            "confidence": "MEDIUM",
            "interview_id": interview.json()["interview"]["id"],
            "related_requirement_id": "REQ-1",
        }),
        content_type="application/json",
        headers=headers("research-finding-1"),
    )
    assert finding.status_code == 201

    question = client.post(
        f"/api/v1/product/user-research/{research.id}/questions/create/",
        data=json.dumps({"question": "Is the hesitation specific to first-time desktop users?"}),
        content_type="application/json",
        headers=headers("research-question-1"),
    )
    assert question.status_code == 201
    question_id = question.json()["question"]["id"]

    resolved = client.post(
        f"/api/v1/product/user-research/questions/{question_id}/update/",
        data=json.dumps({"status": "RESOLVED", "resolution_note": "Deferred to the desktop-only beta slice."}),
        content_type="application/json",
        headers=headers("research-question-2"),
    )
    assert resolved.status_code == 200
    assert resolved.json()["question"]["status"] == UserResearchQuestion.Status.RESOLVED

    listed = client.get(f"/api/v1/product/spec-contracts/{contract.id}/user-research/")
    assert listed.status_code == 200
    record = listed.json()["user_research_contracts"][0]
    assert len(record["interviews"]) == 1
    assert len(record["findings"]) == 1
    assert record["questions"][0]["status"] == "RESOLVED"
    assert listed.json()["no_customer_contact"] is True


def test_user_research_rejects_customer_contact_and_direct_channels(client, spec_contract):
    contract, _objective, _project = spec_contract
    url = f"/api/v1/product/spec-contracts/{contract.id}/user-research/create/"
    response = client.post(
        url,
        data=json.dumps({
            "title": "Outreach plan",
            "research_question": "Should we email users?",
            "contact_customer": True,
            "email": "person@example.com",
        }),
        content_type="application/json",
        headers=headers("research-contact"),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PRODUCT_CONTRACT_BLOCKED"
    assert UserResearchContract.objects.count() == 0


def test_user_research_rejects_cancelled_spec(client, spec_contract):
    contract, _objective, _project = spec_contract
    contract.status = ProductSpecContract.Status.CANCELLED
    contract.save(update_fields=["status"])

    response = client.post(
        f"/api/v1/product/spec-contracts/{contract.id}/user-research/create/",
        data=json.dumps({"title": "Late notes", "research_question": "What remains unclear?"}),
        content_type="application/json",
        headers=headers("research-cancelled"),
    )

    assert response.status_code == 409
    assert UserResearchContract.objects.count() == 0


def test_milestone_links_only_to_an_active_objective_for_the_same_project(client, spec_contract):
    _contract, objective, project = spec_contract
    created = client.post(
        "/api/v1/product/milestones/create/",
        data=json.dumps({
            "project_id": str(project.id),
            "name": "Beta onboarding",
            "target_date": "2026-12-01",
            "objective_id": str(objective.id),
        }),
        content_type="application/json",
    )
    assert created.status_code == 201
    assert created.json()["milestone"]["objective_id"] == str(objective.id)

    unlinked = ProductMilestone.objects.create(project=project, name="Later release", target_date=date(2026, 12, 15))
    linked = client.post(
        f"/api/v1/product/milestones/{unlinked.id}/objective/",
        data=json.dumps({"objective_id": str(objective.id)}),
        content_type="application/json",
        headers=headers("milestone-link-1"),
    )
    assert linked.status_code == 200
    assert linked.json()["milestone"]["objective_code"] == "O1"
    assert AuditEvent.objects.filter(action="product.milestone.objective_linked", object_id=str(unlinked.id)).exists()

    other = Objective.objects.create(
        code="O9",
        strategy_version=objective.strategy_version,
        name="Unrelated objective",
        business_outcome="Not linked to this project.",
        status=Objective.Status.ACTIVE,
    )
    blocked = client.post(
        f"/api/v1/product/milestones/{unlinked.id}/objective/",
        data=json.dumps({"objective_id": str(other.id)}),
        content_type="application/json",
        headers=headers("milestone-link-2"),
    )
    assert blocked.status_code == 409
    unlinked.refresh_from_db()
    assert unlinked.objective_id == objective.id

    timeline = client.get(f"/api/v1/product/roadmap/timeline/?project_id={project.id}")
    codes = {item["objective_code"] for item in timeline.json()["roadmap"]}
    assert "O1" in codes


def test_competitive_analysis_stays_internal_until_review(client, spec_contract):
    contract, _objective, _project = spec_contract
    created = client.post(
        f"/api/v1/product/spec-contracts/{contract.id}/competitive-analyses/create/",
        data=json.dumps({
            "title": "Onboarding alternatives",
            "competitor_label": "Desktop trainer category",
            "comparison_points": [{"dimension": "first session", "observation": "Most tools start with a long setup form."}],
            "implications": "Keep the first session to one goal prompt.",
        }),
        content_type="application/json",
        headers=headers("competitive-1"),
    )
    assert created.status_code == 201
    body = created.json()["competitive_analysis"]
    assert body["review_status"] == "NEEDS_REVIEW"
    assert body["no_customer_contact"] is True
    assert body["no_external_write"] is True

    reviewed = client.post(
        f"/api/v1/product/competitive-analyses/{body['id']}/review/",
        data=json.dumps({"decision": "APPROVED"}),
        content_type="application/json",
        headers=headers("competitive-2"),
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["competitive_analysis"]["review_status"] == CompetitiveAnalysisDraft.ReviewStatus.APPROVED
    assert AuditEvent.objects.filter(action="product.competitive_analysis.reviewed").exists()
