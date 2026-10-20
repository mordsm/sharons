import json

import pytest
from django.utils import timezone

from governance.models import ApprovalRequest, ApprovedActionExecution, AuditEvent, RuleEngineRun, RuleEngineWorkItem
from governance.services import create_approval_request, decide_approval_request
from operations.models import Task
from portfolio.models import Objective, StrategyVersion


pytestmark = pytest.mark.django_db


def active_objective():
    strategy = StrategyVersion.objects.create(version=1, title="Strategy", content={}, status=StrategyVersion.Status.ACTIVE, valid_from=timezone.now())
    return Objective.objects.create(
        code="O1",
        strategy_version=strategy,
        name="Mental Trainer readiness",
        business_outcome="Ready for beta",
        status=Objective.Status.ACTIVE,
        owner_agent_id="chief_of_staff",
    )


def approved_transition_approval(task: Task) -> ApprovalRequest:
    payload = {"to_status": Task.Status.APPROVED, "expected_version": task.version}
    approval = create_approval_request(
        subject_type="operations.Task",
        subject_id=str(task.id),
        subject_version=task.version,
        action="operations.task.transition",
        action_payload=payload,
        requested_by="chief_of_staff",
        correlation_id="corr-exec-request",
        expires_at=timezone.now() + timezone.timedelta(hours=1),
    )
    return decide_approval_request(
        str(approval.id),
        decision=ApprovalRequest.Status.APPROVED,
        actor_id="ceo",
        subject_version=task.version,
        action_payload=payload,
        correlation_id="corr-exec-decision",
    )


def approved_rule_engine_review_approval() -> ApprovalRequest:
    run = RuleEngineRun.objects.create(
        source="gmail_mock",
        external_event_id="msg-review-1",
        event_type="inbound_email.route",
        event_payload={"event_type": "inbound_email.route"},
        dry_run=True,
        final_decision="require_approval",
        risk_level="high",
        reason_codes=["SENSITIVE_EMAIL_REQUIRES_HUMAN_REVIEW"],
        approval_required_actions=[
            {
                "action_type": "create_file_link_proposal",
                "title": "File inbound email attachment",
                "component": "sharons_files",
                "purpose": "safe_internal_filing",
            }
        ],
        routes=[{"component": "owner_review", "capability": "approval", "purpose": "review_sensitive_email"}],
        raw_result={"final_decision": "require_approval"},
    )
    payload = {
        "rule_engine_run_id": str(run.id),
        "event_type": run.event_type,
        "final_decision": run.final_decision,
        "dry_run": True,
        "prohibited_external_execution": True,
    }
    approval = create_approval_request(
        subject_type="governance.RuleEngineRun",
        subject_id=str(run.id),
        subject_version=1,
        action="governance.rules_engine.review",
        action_payload=payload,
        requested_by="chief_of_staff",
        correlation_id="corr-rule-engine-review-request",
        expires_at=timezone.now() + timezone.timedelta(hours=1),
        reason_codes=run.reason_codes,
    )
    return decide_approval_request(
        str(approval.id),
        decision=ApprovalRequest.Status.APPROVED,
        actor_id="ceo",
        subject_version=1,
        action_payload=payload,
        correlation_id="corr-rule-engine-review-decision",
    )


def test_approved_action_executor_transitions_task_and_records_execution(client):
    task = Task.objects.create(objective=active_objective(), title="Approve beta task", status=Task.Status.PLANNED, created_by="test")
    approval = approved_transition_approval(task)

    response = client.post(
        f"/api/v1/approvals/{approval.id}/execute/",
        data=json.dumps({}),
        content_type="application/json",
        headers={"Idempotency-Key": "approval-execute-1", "X-Correlation-ID": "corr-execute-1", "X-Actor-ID": "chief_of_staff"},
    )

    assert response.status_code == 200
    task.refresh_from_db()
    assert task.status == Task.Status.APPROVED
    execution = ApprovedActionExecution.objects.get(approval=approval)
    assert execution.status == ApprovedActionExecution.Status.SUCCEEDED
    assert execution.result["task_status"] == Task.Status.APPROVED
    assert response.json()["execution"]["id"] == str(execution.id)
    assert AuditEvent.objects.filter(action="governance.approval.executed", object_id=str(execution.id)).exists()


def test_approved_action_executor_is_idempotent_for_same_request(client):
    task = Task.objects.create(objective=active_objective(), title="Approve beta task", status=Task.Status.PLANNED, created_by="test")
    approval = approved_transition_approval(task)
    headers = {"Idempotency-Key": "approval-execute-2", "X-Correlation-ID": "corr-execute-2"}

    first = client.post(f"/api/v1/approvals/{approval.id}/execute/", data=json.dumps({}), content_type="application/json", headers=headers)
    second = client.post(f"/api/v1/approvals/{approval.id}/execute/", data=json.dumps({}), content_type="application/json", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert ApprovedActionExecution.objects.count() == 1


def test_approved_action_executor_rejects_second_execution_with_new_idempotency_key(client):
    task = Task.objects.create(objective=active_objective(), title="Approve beta task", status=Task.Status.PLANNED, created_by="test")
    approval = approved_transition_approval(task)
    client.post(
        f"/api/v1/approvals/{approval.id}/execute/",
        data=json.dumps({}),
        content_type="application/json",
        headers={"Idempotency-Key": "approval-execute-3a", "X-Correlation-ID": "corr-execute-3a"},
    )

    response = client.post(
        f"/api/v1/approvals/{approval.id}/execute/",
        data=json.dumps({}),
        content_type="application/json",
        headers={"Idempotency-Key": "approval-execute-3b", "X-Correlation-ID": "corr-execute-3b"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "APPROVED_ACTION_ALREADY_EXECUTED"
    assert ApprovedActionExecution.objects.count() == 1


def test_approved_action_executor_rejects_pending_approval(client):
    task = Task.objects.create(objective=active_objective(), title="Approve beta task", status=Task.Status.PLANNED, created_by="test")
    approval = create_approval_request(
        subject_type="operations.Task",
        subject_id=str(task.id),
        subject_version=task.version,
        action="operations.task.transition",
        action_payload={"to_status": Task.Status.APPROVED, "expected_version": task.version},
        requested_by="chief_of_staff",
        correlation_id="corr-exec-pending",
        expires_at=timezone.now() + timezone.timedelta(hours=1),
    )

    response = client.post(
        f"/api/v1/approvals/{approval.id}/execute/",
        data=json.dumps({}),
        content_type="application/json",
        headers={"Idempotency-Key": "approval-execute-4", "X-Correlation-ID": "corr-execute-4"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "APPROVED_ACTION_EXECUTION_ERROR"
    assert ApprovedActionExecution.objects.count() == 0


def test_approved_action_executor_materializes_rule_engine_review_items(client):
    approval = approved_rule_engine_review_approval()

    response = client.post(
        f"/api/v1/approvals/{approval.id}/execute/",
        data=json.dumps({}),
        content_type="application/json",
        headers={"Idempotency-Key": "approval-execute-rules-1", "X-Correlation-ID": "corr-execute-rules-1", "X-Actor-ID": "chief_of_staff"},
    )

    assert response.status_code == 200
    execution = ApprovedActionExecution.objects.get(approval=approval)
    assert execution.status == ApprovedActionExecution.Status.SUCCEEDED
    assert execution.result["external_action_executed"] is False
    assert execution.result["created_internal_items"][0]["item_type"] == "APPROVAL_REQUIRED_ACTION"
    assert execution.result["created_internal_items"][0]["no_external_action"] is True
    work_items = list(RuleEngineWorkItem.objects.filter(execution=execution).order_by("item_type"))
    assert len(work_items) == 2
    by_type = {item.item_type: item for item in work_items}
    assert by_type["APPROVAL_REQUIRED_ACTION"].owner_agent_id == "executive_assistant"
    assert by_type["APPROVAL_REQUIRED_ACTION"].status == RuleEngineWorkItem.Status.ASSIGNED
    assert by_type["ROUTE_REVIEW"].owner_agent_id == "chief_of_staff"
    assert by_type["ROUTE_REVIEW"].status == RuleEngineWorkItem.Status.ASSIGNED
    assert execution.result["created_work_item_ids"]
    assert AuditEvent.objects.filter(action="governance.rules_engine.review.executed", object_id=str(execution.id)).exists()
    assert AuditEvent.objects.filter(action="governance.rules_engine.work_item.created").count() == 2
    assert AuditEvent.objects.filter(action="governance.approval.executed", object_id=str(execution.id)).exists()
