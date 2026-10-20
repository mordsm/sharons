import pytest
from django.contrib.auth.models import Permission, User
from django.utils import timezone

from governance.models import ApprovalRequest
from governance.services import create_approval_request


def create_dashboard_approval(**overrides):
    defaults = {
        "subject_type": "operations.Task",
        "subject_id": "task-dashboard-1",
        "subject_version": 1,
        "action": "operations.task.complete",
        "action_payload": {"status": "COMPLETED"},
        "requested_by": "chief_of_staff",
        "correlation_id": "corr-dashboard-request",
        "expires_at": timezone.now() + timezone.timedelta(hours=1),
    }
    defaults.update(overrides)
    return create_approval_request(**defaults)


@pytest.fixture
def approval_viewer():
    user = User.objects.create_user(username="viewer", password="password")
    user.user_permissions.add(Permission.objects.get(codename="view_approvalrequest"))
    return user


@pytest.fixture
def approval_decider():
    user = User.objects.create_user(username="ceo", password="password")
    user.user_permissions.add(Permission.objects.get(codename="view_approvalrequest"))
    user.user_permissions.add(Permission.objects.get(codename="decide_approvalrequest"))
    return user


@pytest.mark.django_db
def test_approval_inbox_requires_login(client):
    response = client.get("/approvals/")

    assert response.status_code == 302
    assert response["Location"].startswith("/admin/login/")


@pytest.mark.django_db
def test_approval_inbox_renders_pending_approvals(client, approval_viewer):
    approval = create_dashboard_approval()
    client.force_login(approval_viewer)

    response = client.get("/approvals/")

    assert response.status_code == 200
    assert b"Approval Inbox" in response.content
    assert str(approval.id).encode("utf-8") in response.content
    assert b"task-dashboard-1" in response.content


@pytest.mark.django_db
def test_approval_detail_renders_binding_information(client, approval_viewer):
    approval = create_dashboard_approval()
    client.force_login(approval_viewer)

    response = client.get(f"/approvals/{approval.id}/")

    assert response.status_code == 200
    assert b"Approval Request" in response.content
    assert approval.action_payload_hash.encode("utf-8") in response.content
    assert b"Exact action payload JSON" in response.content


@pytest.mark.django_db
def test_approval_dashboard_rejects_viewer_without_decision_permission(client, approval_viewer):
    approval = create_dashboard_approval()
    client.force_login(approval_viewer)

    response = client.post(
        f"/approvals/{approval.id}/",
        data={
            "decision": ApprovalRequest.Status.APPROVED,
            "subject_version": "1",
            "action_payload": '{"status":"COMPLETED"}',
        },
    )

    assert response.status_code == 403
    approval.refresh_from_db()
    assert approval.status == ApprovalRequest.Status.PENDING


@pytest.mark.django_db
def test_approval_dashboard_rejects_wrong_payload(client, approval_decider):
    approval = create_dashboard_approval()
    client.force_login(approval_decider)

    response = client.post(
        f"/approvals/{approval.id}/",
        data={
            "decision": ApprovalRequest.Status.APPROVED,
            "subject_version": "1",
            "action_payload": '{"status":"FAILED"}',
        },
    )

    assert response.status_code == 409
    approval.refresh_from_db()
    assert approval.status == ApprovalRequest.Status.PENDING


@pytest.mark.django_db
def test_approval_dashboard_approves_exact_payload(client, approval_decider):
    approval = create_dashboard_approval()
    client.force_login(approval_decider)

    response = client.post(
        f"/approvals/{approval.id}/",
        data={
            "decision": ApprovalRequest.Status.APPROVED,
            "subject_version": "1",
            "action_payload": '{"status":"COMPLETED"}',
        },
    )

    assert response.status_code == 302
    approval.refresh_from_db()
    assert approval.status == ApprovalRequest.Status.APPROVED
    assert approval.decided_by == "ceo"
