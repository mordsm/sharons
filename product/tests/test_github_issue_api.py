import json

import pytest

from governance.models import ApprovalRequest, SecretReference
from portfolio.models import Project, ProjectConnection
from product.models import GithubIssueRequest


pytestmark = pytest.mark.django_db


def headers(key: str) -> dict:
    return {"Idempotency-Key": key, "X-Correlation-ID": f"corr-{key}", "X-Actor-ID": "product_manager"}


@pytest.fixture
def github_project():
    project = Project.objects.create(
        name="Mental Trainer",
        slug="mental-trainer",
        status=Project.Status.ACTIVE,
        repository_reference="https://github.com/sharons/mental-trainer",
        owner="chief_of_staff",
    )
    connection = ProjectConnection.objects.create(
        project=project,
        connection_type=ProjectConnection.ConnectionType.ISSUE_TRACKER,
        adapter_type="github_issues",
        permission_mode=ProjectConnection.PermissionMode.WRITE_APPROVED,
        capabilities={"create_issue": True},
    )
    SecretReference.objects.create(
        name="github-issues",
        purpose=SecretReference.Purpose.GITHUB_ISSUE_CREATE,
        provider="github",
        env_var_name="SHARONS_GITHUB_TOKEN",
        created_by="product_manager",
    )
    return project, connection


def test_github_issue_request_does_not_call_github(client, github_project, monkeypatch):
    project, _connection = github_project
    monkeypatch.setattr("executive_assistant.provider_http.http_json", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("called")))

    response = client.post(
        "/api/v1/product/github-issues/create/",
        data=json.dumps({
            "project_id": str(project.id),
            "title": "Beta onboarding gap",
            "body": "Track the approved onboarding requirement.",
            "secret_reference_name": "github-issues",
        }),
        content_type="application/json",
        headers=headers("github-create"),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["external_call"] is False
    assert body["github_issue_request"]["allowed_action"] == "create_issue"
    assert body["github_issue_request"]["repository_owner"] == "sharons"
    assert body["github_issue_request"]["status"] == "DRAFT"
    assert GithubIssueRequest.objects.get().issue_number is None


def test_approved_github_issue_posts_only_create_issue(client, github_project, monkeypatch):
    project, _connection = github_project
    monkeypatch.setenv("SHARONS_GITHUB_TOKEN", "github-test-token")
    calls = []

    def fake_http(method, url, *, token, payload=None):
        calls.append((method, url, token, payload))
        return {"number": 41, "html_url": "https://github.com/sharons/mental-trainer/issues/41"}

    monkeypatch.setattr("executive_assistant.provider_http.http_json", fake_http)
    created = client.post(
        "/api/v1/product/github-issues/create/",
        data=json.dumps({
            "project_id": str(project.id),
            "title": "Beta onboarding gap",
            "body": "Track the approved onboarding requirement.",
            "secret_reference_name": "github-issues",
        }),
        content_type="application/json",
        headers=headers("github-create-2"),
    )
    issue = created.json()["github_issue_request"]
    requested = client.post(
        f"/api/v1/product/github-issues/{issue['id']}/approval-request/",
        data=json.dumps({}),
        content_type="application/json",
        headers=headers("github-approval"),
    )
    assert requested.status_code == 200
    approval = ApprovalRequest.objects.get()
    decision = client.post(
        f"/api/v1/approvals/{approval.id}/decision/",
        data=json.dumps({
            "decision": "APPROVED",
            "subject_version": approval.subject_version,
            "action_payload": approval.action_payload,
        }),
        content_type="application/json",
        headers=headers("github-decide"),
    )
    assert decision.status_code == 200
    executed = client.post(
        f"/api/v1/approvals/{approval.id}/execute/",
        data=json.dumps({}),
        content_type="application/json",
        headers=headers("github-execute"),
    )

    assert executed.status_code == 200
    assert calls == [(
        "POST",
        "https://api.github.com/repos/sharons/mental-trainer/issues",
        "github-test-token",
        {"title": "Beta onboarding gap", "body": "Track the approved onboarding requirement."},
    )]
    stored = GithubIssueRequest.objects.get()
    assert stored.status == GithubIssueRequest.Status.CREATED
    assert stored.issue_number == 41


def test_github_issue_requires_write_approved_connection(client):
    project = Project.objects.create(
        name="Mental Trainer",
        slug="mental-trainer-readonly",
        status=Project.Status.ACTIVE,
        repository_reference="https://github.com/sharons/mental-trainer",
        owner="chief_of_staff",
    )
    ProjectConnection.objects.create(
        project=project,
        connection_type=ProjectConnection.ConnectionType.REPOSITORY,
        adapter_type="github_issues",
        permission_mode=ProjectConnection.PermissionMode.READ_ONLY,
        capabilities={"create_issue": True},
    )

    response = client.post(
        "/api/v1/product/github-issues/create/",
        data=json.dumps({
            "project_id": str(project.id),
            "title": "Should not create",
            "body": "Read-only connection.",
            "secret_reference_name": "github-issues",
        }),
        content_type="application/json",
        headers=headers("github-readonly"),
    )

    assert response.status_code == 409
    assert GithubIssueRequest.objects.count() == 0
