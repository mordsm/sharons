import json

import pytest

from governance.models import AuditEvent
from portfolio.models import ObjectiveProjectLink, Project, ProjectConnection, ProjectStateAssessment


@pytest.mark.django_db
def test_projects_collection_creates_project_with_audit(client):
    response = client.post(
        "/api/v1/projects/",
        data=json.dumps(
            {
                "slug": "research-manager",
                "name": "Research Manager",
                "owner": "chief_of_staff",
                "status": Project.Status.ACTIVE,
                "repository_provider": "local",
                "repository_reference": "C:\\workspace\\research_manager",
                "default_branch": "main",
                "metadata": {"stack": ["FastAPI", "LangGraph", "Pydantic", "SQLite"]},
            }
        ),
        content_type="application/json",
        headers={"Idempotency-Key": "project-1", "X-Correlation-ID": "corr-project-1"},
    )

    assert response.status_code == 201
    project = Project.objects.get(slug="research-manager")
    assert response.json()["project"]["id"] == str(project.id)
    assert project.repository_reference == "C:\\workspace\\research_manager"
    assert AuditEvent.objects.filter(
        object_id=str(project.id),
        action="portfolio.project.created",
        correlation_id="corr-project-1",
    ).exists()


@pytest.mark.django_db
def test_projects_collection_lists_projects(client):
    Project.objects.create(slug="research-manager", name="Research Manager", owner="chief_of_staff")

    response = client.get("/api/v1/projects/")

    assert response.status_code == 200
    assert response.json()["projects"][0]["slug"] == "research-manager"


@pytest.mark.django_db
def test_projects_collection_is_idempotent(client):
    payload = {"slug": "research-manager", "name": "Research Manager", "owner": "chief_of_staff"}
    headers = {"Idempotency-Key": "project-2", "X-Correlation-ID": "corr-project-2"}

    first = client.post("/api/v1/projects/", data=json.dumps(payload), content_type="application/json", headers=headers)
    second = client.post("/api/v1/projects/", data=json.dumps(payload), content_type="application/json", headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()
    assert Project.objects.count() == 1
    assert AuditEvent.objects.count() == 1


@pytest.mark.django_db
def test_projects_collection_rejects_missing_required_fields(client):
    response = client.post(
        "/api/v1/projects/",
        data=json.dumps({"slug": "research-manager"}),
        content_type="application/json",
        headers={"Idempotency-Key": "project-3", "X-Correlation-ID": "corr-project-3"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PROJECT_PAYLOAD"


@pytest.mark.django_db
def test_project_connection_create_defaults_to_read_only(client):
    project = Project.objects.create(slug="research-manager", name="Research Manager", owner="chief_of_staff")

    response = client.post(
        f"/api/v1/projects/{project.id}/connections/",
        data=json.dumps(
            {
                "connection_type": ProjectConnection.ConnectionType.REPOSITORY,
                "adapter_type": "local_repository",
                "capabilities": {"status": True, "summaries": True},
            }
        ),
        content_type="application/json",
        headers={"Idempotency-Key": "connection-1", "X-Correlation-ID": "corr-connection-1"},
    )

    assert response.status_code == 201
    connection = ProjectConnection.objects.get(project=project)
    assert connection.permission_mode == ProjectConnection.PermissionMode.READ_ONLY
    assert response.json()["connection"]["permission_mode"] == ProjectConnection.PermissionMode.READ_ONLY
    assert AuditEvent.objects.filter(
        object_id=str(connection.id),
        action="portfolio.project_connection.created",
        correlation_id="corr-connection-1",
    ).exists()


@pytest.mark.django_db
def test_project_connection_create_rejects_missing_project(client):
    response = client.post(
        "/api/v1/projects/00000000-0000-0000-0000-000000000000/connections/",
        data=json.dumps({"connection_type": ProjectConnection.ConnectionType.REPOSITORY, "adapter_type": "local_repository"}),
        content_type="application/json",
        headers={"Idempotency-Key": "connection-2", "X-Correlation-ID": "corr-connection-2"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROJECT_NOT_FOUND"


@pytest.mark.django_db
def test_known_90_day_projects_register_links_existing_project_map(client):
    headers = {"Idempotency-Key": "known-90-1", "X-Correlation-ID": "corr-known-90-1", "X-Actor-ID": "chief_of_staff"}

    first = client.post("/api/v1/projects/known-90-day/register/", data=json.dumps({}), content_type="application/json", headers=headers)
    second = client.post("/api/v1/projects/known-90-day/register/", data=json.dumps({}), content_type="application/json", headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()
    body = first.json()
    slugs = {project["slug"] for project in body["projects"]}
    assert {"mental-skills-playground", "economic-manager", "administrative-agent", "rules-engine"}.issubset(slugs)
    assert ObjectiveProjectLink.objects.filter(objective__code="O1", project__slug="mental-skills-playground").exists()
    assert ObjectiveProjectLink.objects.filter(objective__code="O2", project__slug="economic-manager").exists()
    assert ObjectiveProjectLink.objects.filter(objective__code="O3", project__slug="administrative-agent").exists()
    assert ObjectiveProjectLink.objects.filter(objective__code="O4", project__slug="rules-engine").exists()
    assert ProjectStateAssessment.objects.filter(status=ProjectStateAssessment.Status.CURRENT).count() == len(body["projects"])
    assert AuditEvent.objects.filter(action="portfolio.known_90_day_projects.registered", correlation_id="corr-known-90-1").count() == 1


@pytest.mark.django_db
def test_objective_links_and_assessments_are_listable(client):
    client.post(
        "/api/v1/projects/known-90-day/register/",
        data=json.dumps({}),
        content_type="application/json",
        headers={"Idempotency-Key": "known-90-2", "X-Correlation-ID": "corr-known-90-2"},
    )

    links_response = client.get("/api/v1/projects/objective-links/", {"objective_code": "O2"})
    assessments_response = client.get("/api/v1/projects/state-assessments/", {"project_slug": "economic-manager"})

    assert links_response.status_code == 200
    assert {link["project_slug"] for link in links_response.json()["links"]} >= {"economic-manager", "mail-manager"}
    assert assessments_response.status_code == 200
    assessments = assessments_response.json()["assessments"]
    assert assessments[0]["project_slug"] == "economic-manager"
    assert "not from scratch" in assessments[0]["summary"]
