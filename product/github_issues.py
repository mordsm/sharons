import re
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from core.services import canonical_hash
from governance.models import AuditEvent
from governance.secrets import SecretNotConfiguredError, resolve_secret_value
from governance.services import create_approval_request
from portfolio.models import Project, ProjectConnection
from product.models import GithubIssueRequest
from product.services import InvalidProductContractPayloadError, ProductContractBlockedError


GITHUB_ISSUE_ACTION = "product.github.issue.create"
REPO_PART = re.compile(r"^[A-Za-z0-9_.-]+$")


def parse_github_repository(reference: str) -> tuple[str, str]:
    text = reference.strip()
    text = re.sub(r"^https?://github\.com/", "", text)
    text = text.removesuffix(".git").strip("/")
    parts = [part for part in text.split("/") if part]
    if len(parts) != 2 or not REPO_PART.fullmatch(parts[0]) or not REPO_PART.fullmatch(parts[1]):
        raise InvalidProductContractPayloadError("repository_reference must be a GitHub owner/repo.")
    return parts[0], parts[1]


def issue_action_payload(issue: GithubIssueRequest) -> dict:
    return {
        "issue_request_id": str(issue.id),
        "repository_owner": issue.repository_owner,
        "repository_name": issue.repository_name,
        "title": issue.title,
        "body": issue.body,
        "action": "create_issue",
    }


def serialize_github_issue_request(issue: GithubIssueRequest) -> dict:
    return {
        "id": str(issue.id),
        "project_id": str(issue.project_id),
        "project_connection_id": issue.project_connection_id,
        "title": issue.title,
        "body": issue.body,
        "repository_owner": issue.repository_owner,
        "repository_name": issue.repository_name,
        "secret_reference_name": issue.secret_reference_name,
        "status": issue.status,
        "version": issue.version,
        "allowed_action": issue.allowed_action,
        "approval_request_id": str(issue.approval_request_id) if issue.approval_request_id else None,
        "issue_number": issue.issue_number,
        "issue_url": issue.issue_url,
        "created_by": issue.created_by,
        "created_at": issue.created_at.isoformat(),
    }


def _approved_connection(project: Project, connection_id) -> ProjectConnection:
    connections = ProjectConnection.objects.select_for_update().filter(
        project=project,
        active=True,
        permission_mode=ProjectConnection.PermissionMode.WRITE_APPROVED,
        adapter_type="github_issues",
    )
    if connection_id:
        connection = connections.get(id=int(connection_id))
    else:
        connection = connections.first()
    if connection is None:
        raise ProductContractBlockedError("GitHub issue creation requires an active write-approved github_issues connection.")
    capabilities = connection.capabilities if isinstance(connection.capabilities, dict) else {}
    if capabilities.get("create_issue") is not True:
        raise ProductContractBlockedError("The GitHub connection must allow only the create_issue capability.")
    return connection


def create_github_issue_request(payload: dict, *, actor_id: str, correlation_id: str) -> GithubIssueRequest:
    project_id = str(payload.get("project_id", "")).strip()
    title = str(payload.get("title", "")).strip()
    body = str(payload.get("body", "")).strip()
    secret_reference_name = str(payload.get("secret_reference_name", "")).strip()
    if not project_id or not title or not body or not secret_reference_name:
        raise InvalidProductContractPayloadError("project_id, title, body and secret_reference_name are required.")
    if payload.get("action") not in (None, "", "create_issue"):
        raise ProductContractBlockedError("The only approved GitHub action is create_issue.")
    actor = actor_id.strip() or "api"
    with transaction.atomic():
        project = Project.objects.select_for_update().get(id=project_id)
        connection = _approved_connection(project, payload.get("project_connection_id"))
        owner, repo = parse_github_repository(project.repository_reference)
        issue = GithubIssueRequest.objects.create(
            project=project,
            project_connection=connection,
            title=title,
            body=body,
            repository_owner=owner,
            repository_name=repo,
            secret_reference_name=secret_reference_name,
            created_by=actor,
        )
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="product.github_issue.requested",
            object_type="product.GithubIssueRequest",
            object_id=str(issue.id),
            correlation_id=correlation_id,
            metadata={"allowed_action": "create_issue", "external_call": False},
        )
    return issue


def request_github_issue_approval(payload: dict, *, issue_id: str, actor_id: str, correlation_id: str) -> GithubIssueRequest:
    actor = actor_id.strip() or "api"
    with transaction.atomic():
        issue = GithubIssueRequest.objects.select_for_update().get(id=issue_id)
        if issue.status != GithubIssueRequest.Status.DRAFT:
            raise ProductContractBlockedError("Only a draft GitHub issue request can be sent for approval.")
        action_payload = issue_action_payload(issue)
        approval = create_approval_request(
            subject_type="product.GithubIssueRequest",
            subject_id=str(issue.id),
            subject_version=issue.version,
            action=GITHUB_ISSUE_ACTION,
            action_payload=action_payload,
            requested_by=actor,
            correlation_id=correlation_id,
            expires_at=timezone.now() + timedelta(days=7),
            reason_codes=["GITHUB_ISSUE_CREATE"],
        )
        issue.status = GithubIssueRequest.Status.PENDING_APPROVAL
        issue.approval_request_id = approval.id
        issue.save(update_fields=["status", "approval_request_id"])
    return issue


def execute_approved_github_issue(approval) -> dict:
    if approval.action != GITHUB_ISSUE_ACTION or approval.subject_type != "product.GithubIssueRequest":
        raise ProductContractBlockedError("Approval is not a GitHub issue creation.")
    issue = GithubIssueRequest.objects.select_for_update().select_related("project", "project_connection").get(id=approval.subject_id)
    if issue.allowed_action != "create_issue":
        raise ProductContractBlockedError("The only approved GitHub action is create_issue.")
    if issue.project_connection.permission_mode != ProjectConnection.PermissionMode.WRITE_APPROVED or not issue.project_connection.active:
        raise ProductContractBlockedError("GitHub issue creation requires an active write-approved connection.")
    expected = issue_action_payload(issue)
    if canonical_hash(expected) != approval.action_payload_hash or approval.subject_version != issue.version:
        raise ProductContractBlockedError("GitHub issue approval does not match the current issue request.")
    from executive_assistant.provider_http import ProviderHttpError, http_json

    url = f"https://api.github.com/repos/{issue.repository_owner}/{issue.repository_name}/issues"
    try:
        token = resolve_secret_value(
            name=issue.secret_reference_name,
            purpose="GITHUB_ISSUE_CREATE",
            provider="github",
        )
        response = http_json("POST", url, token=token, payload={"title": issue.title, "body": issue.body})
    except (SecretNotConfiguredError, ProviderHttpError) as exc:
        raise ProductContractBlockedError(str(exc)) from exc
    issue_number = response.get("number")
    issue_url = str(response.get("html_url", "")).strip()
    if not isinstance(issue_number, int) or not issue_url.startswith("https://github.com/"):
        raise ProductContractBlockedError("GitHub did not return an issue number and URL.")
    issue.status = GithubIssueRequest.Status.CREATED
    issue.issue_number = issue_number
    issue.issue_url = issue_url
    issue.save(update_fields=["status", "issue_number", "issue_url"])
    return {"issue_request_id": str(issue.id), "issue_number": issue_number, "issue_url": issue_url, "allowed_action": "create_issue"}
