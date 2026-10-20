from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
import sys
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.services import canonical_hash
from governance.models import ApprovalRequest, ApprovedActionExecution, AuditEvent, InboxEvent, OutboxMessage, Rule, RuleEngineRun, RuleEngineWorkItem, RuleEvaluation, RuleTestCase


class RuleEngineError(Exception):
    code = "RULE_ENGINE_ERROR"


class InvalidRuleConditionError(RuleEngineError):
    code = "INVALID_RULE_CONDITION"


class InvalidRulePayloadError(RuleEngineError):
    code = "INVALID_RULE_PAYLOAD"


class InvalidRuleEventPayloadError(RuleEngineError):
    code = "INVALID_RULE_EVENT_PAYLOAD"


class RuleEngineUnavailableError(RuleEngineError):
    code = "RULE_ENGINE_UNAVAILABLE"


class RuleLifecycleError(RuleEngineError):
    code = "RULE_LIFECYCLE_ERROR"


class RuleTestFailedError(RuleLifecycleError):
    code = "RULE_TEST_FAILED"


class RuleActivationApprovalError(RuleLifecycleError):
    code = "RULE_ACTIVATION_APPROVAL_REQUIRED"


class ApprovalError(Exception):
    code = "APPROVAL_ERROR"


class ApprovalExpiredError(ApprovalError):
    code = "APPROVAL_EXPIRED"


class ApprovalPayloadMismatchError(ApprovalError):
    code = "APPROVAL_PAYLOAD_MISMATCH"


class ApprovalVersionMismatchError(ApprovalError):
    code = "APPROVAL_VERSION_MISMATCH"


class ApprovalAlreadyDecidedError(ApprovalError):
    code = "APPROVAL_ALREADY_DECIDED"


class InvalidApprovalDecisionError(ApprovalError):
    code = "INVALID_APPROVAL_DECISION"


class ApprovedActionExecutionError(ApprovalError):
    code = "APPROVED_ACTION_EXECUTION_ERROR"


class ApprovedActionAlreadyExecutedError(ApprovedActionExecutionError):
    code = "APPROVED_ACTION_ALREADY_EXECUTED"


class UnsupportedApprovedActionError(ApprovedActionExecutionError):
    code = "UNSUPPORTED_APPROVED_ACTION"


class RuleEngineWorkItemError(ApprovalError):
    code = "RULE_ENGINE_WORK_ITEM_ERROR"


class InvalidRuleEngineWorkItemUpdateError(RuleEngineWorkItemError):
    code = "INVALID_RULE_ENGINE_WORK_ITEM_UPDATE"


class OutboxError(Exception):
    code = "OUTBOX_ERROR"


class InvalidOutboxPayloadError(OutboxError):
    code = "INVALID_OUTBOX_PAYLOAD"


class OutboxIdempotencyConflictError(OutboxError):
    code = "OUTBOX_IDEMPOTENCY_CONFLICT"


class OutboxRecoveryError(OutboxError):
    code = "OUTBOX_RECOVERY_ERROR"


class InboxError(Exception):
    code = "INBOX_ERROR"


class InvalidInboxPayloadError(InboxError):
    code = "INVALID_INBOX_PAYLOAD"


ALLOWED_OPERATORS = {
    "equals",
    "not_equals",
    "less_than",
    "less_or_equal",
    "greater_than",
    "greater_or_equal",
    "in",
    "not_in",
    "exists",
}


@dataclass(frozen=True)
class EvaluationResult:
    decision: str
    rule: Rule | None
    matched_paths: list[str]
    reason_codes: list[str]


APPROVAL_VIEWER_GROUP = "approval_viewers"
APPROVAL_DECIDER_GROUP = "approval_deciders"


def provision_approval_groups() -> dict[str, list[str]]:
    content_type = ContentType.objects.get_for_model(ApprovalRequest)
    view_permission = Permission.objects.get(content_type=content_type, codename="view_approvalrequest")
    decide_permission = Permission.objects.get(content_type=content_type, codename="decide_approvalrequest")

    viewer_group, _viewer_created = Group.objects.get_or_create(name=APPROVAL_VIEWER_GROUP)
    decider_group, _decider_created = Group.objects.get_or_create(name=APPROVAL_DECIDER_GROUP)

    viewer_group.permissions.set([view_permission])
    decider_group.permissions.set([view_permission, decide_permission])

    return {
        viewer_group.name: sorted(viewer_group.permissions.values_list("codename", flat=True)),
        decider_group.name: sorted(decider_group.permissions.values_list("codename", flat=True)),
    }


def setup_ceo_reviewer(*, username: str, email: str = "", password: str = "") -> tuple[object, bool]:
    username = username.strip()
    if not username:
        raise ValueError("username is required.")

    provision_approval_groups()
    user_model = get_user_model()
    user, created = user_model.objects.get_or_create(username=username, defaults={"email": email.strip()})

    changed_fields: list[str] = []
    if email.strip() and user.email != email.strip():
        user.email = email.strip()
        changed_fields.append("email")

    if password:
        user.set_password(password)
        changed_fields.append("password")
    elif created:
        user.set_unusable_password()
        changed_fields.append("password")

    if changed_fields:
        user.save(update_fields=changed_fields)

    decider_group = Group.objects.get(name=APPROVAL_DECIDER_GROUP)
    user.groups.add(decider_group)
    return user, created


def serialize_approval_request(approval: ApprovalRequest) -> dict:
    return {
        "id": str(approval.id),
        "subject_type": approval.subject_type,
        "subject_id": approval.subject_id,
        "subject_version": approval.subject_version,
        "action": approval.action,
        "action_payload": approval.action_payload,
        "action_payload_hash": approval.action_payload_hash,
        "requested_by": approval.requested_by,
        "status": approval.status,
        "reason_codes": approval.reason_codes,
        "expires_at": approval.expires_at.isoformat(),
        "decided_by": approval.decided_by,
        "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
        "created_at": approval.created_at.isoformat(),
    }


def serialize_approved_action_execution(execution: ApprovedActionExecution) -> dict:
    return {
        "id": str(execution.id),
        "approval_id": str(execution.approval_id),
        "action": execution.action,
        "status": execution.status,
        "result": execution.result,
        "error_code": execution.error_code,
        "error_message": execution.error_message,
        "executed_by": execution.executed_by,
        "correlation_id": execution.correlation_id,
        "executed_at": execution.executed_at.isoformat(),
    }


def serialize_outbox_message(message: OutboxMessage) -> dict:
    return {
        "id": str(message.id),
        "topic": message.topic,
        "payload": message.payload,
        "status": message.status,
        "attempts": message.attempts,
        "next_attempt_at": message.next_attempt_at.isoformat() if message.next_attempt_at else None,
        "idempotency_key": message.idempotency_key,
        "correlation_id": message.correlation_id,
        "created_at": message.created_at.isoformat(),
        "updated_at": message.updated_at.isoformat(),
    }


def serialize_inbox_event(event: InboxEvent) -> dict:
    return {
        "id": str(event.id),
        "source": event.source,
        "external_event_id": event.external_event_id,
        "payload": event.payload,
        "status": event.status,
        "received_at": event.received_at.isoformat(),
        "processed_at": event.processed_at.isoformat() if event.processed_at else None,
        "correlation_id": event.correlation_id,
    }


def serialize_audit_event(event: AuditEvent) -> dict:
    return {
        "id": str(event.id),
        "occurred_at": event.occurred_at.isoformat(),
        "actor_type": event.actor_type,
        "actor_id": event.actor_id,
        "action": event.action,
        "object_type": event.object_type,
        "object_id": event.object_id,
        "before_hash": event.before_hash,
        "after_hash": event.after_hash,
        "correlation_id": event.correlation_id,
        "causation_id": event.causation_id,
        "metadata": event.metadata,
    }


def serialize_rule(rule: Rule) -> dict:
    return {
        "id": str(rule.id),
        "rule_id": rule.rule_id,
        "version": rule.version,
        "name": rule.name,
        "owner": rule.owner,
        "status": rule.status,
        "trigger": rule.trigger,
        "conditions": rule.conditions,
        "decision": rule.decision,
        "reason_codes": rule.reason_codes,
        "schema_version": rule.schema_version,
        "approved_by": rule.approved_by,
        "approved_at": rule.approved_at.isoformat() if rule.approved_at else None,
        "valid_from": rule.valid_from.isoformat() if rule.valid_from else None,
        "expires_at": rule.expires_at.isoformat() if rule.expires_at else None,
        "created_at": rule.created_at.isoformat(),
    }


def serialize_rule_test_case(test_case: RuleTestCase) -> dict:
    return {
        "id": str(test_case.id),
        "rule_id": str(test_case.rule_id),
        "name": test_case.name,
        "input_event": test_case.input_event,
        "expected_decision": test_case.expected_decision,
        "expected_match": test_case.expected_match,
        "passed": test_case.passed,
        "actual_decision": test_case.actual_decision,
        "matched_paths": test_case.matched_paths,
        "created_at": test_case.created_at.isoformat(),
    }


def serialize_rule_evaluation(evaluation: RuleEvaluation) -> dict:
    return {
        "id": str(evaluation.id),
        "event_id": evaluation.event_id,
        "rule_id": str(evaluation.rule_id) if evaluation.rule_id else None,
        "decision": evaluation.decision,
        "matched_paths": evaluation.matched_paths,
        "reason_codes": evaluation.reason_codes,
        "input_snapshot_hash": evaluation.input_snapshot_hash,
        "evaluated_at": evaluation.evaluated_at.isoformat(),
    }


def serialize_rule_engine_run(run: RuleEngineRun, *, include_raw: bool = False) -> dict:
    approval = ApprovalRequest.objects.filter(subject_type="governance.RuleEngineRun", subject_id=str(run.id)).first()
    payload = {
        "id": str(run.id),
        "source": run.source,
        "external_event_id": run.external_event_id,
        "event_type": run.event_type,
        "event_payload": run.event_payload,
        "dry_run": run.dry_run,
        "final_decision": run.final_decision,
        "risk_level": run.risk_level,
        "reason_codes": run.reason_codes,
        "matched_rules": run.matched_rules,
        "allowed_actions": run.allowed_actions,
        "approval_required_actions": run.approval_required_actions,
        "blocked_actions": run.blocked_actions,
        "routes": run.routes,
        "approval_id": str(approval.id) if approval else None,
        "approval_status": approval.status if approval else None,
        "approval_action": approval.action if approval else None,
        "created_at": run.created_at.isoformat(),
    }
    if include_raw:
        payload["raw_result"] = run.raw_result
    return payload


def serialize_rule_engine_work_item(item: RuleEngineWorkItem) -> dict:
    return {
        "id": str(item.id),
        "run_id": str(item.run_id),
        "execution_id": str(item.execution_id) if item.execution_id else None,
        "item_type": item.item_type,
        "action_type": item.action_type,
        "title": item.title,
        "component": item.component,
        "purpose": item.purpose,
        "reason_code": item.reason_code,
        "payload": item.payload,
        "status": item.status,
        "owner_agent_id": item.owner_agent_id,
        "no_external_action": item.no_external_action,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


def list_rule_engine_runs(*, source: str = "", event_type: str = "", final_decision: str = "", limit: int = 100):
    runs = RuleEngineRun.objects.order_by("-created_at")
    if source:
        runs = runs.filter(source=source)
    if event_type:
        runs = runs.filter(event_type=event_type)
    if final_decision:
        runs = runs.filter(final_decision=final_decision)
    return runs[:limit]


def list_rule_engine_work_items(*, status: str = "", owner_agent_id: str = "", item_type: str = "", limit: int = 100):
    items = RuleEngineWorkItem.objects.select_related("run", "execution").order_by("-created_at")
    if status:
        items = items.filter(status=status)
    if owner_agent_id:
        items = items.filter(owner_agent_id=owner_agent_id)
    if item_type:
        items = items.filter(item_type=item_type)
    return items[:limit]


def search_audit_events(
    *,
    action: str = "",
    object_type: str = "",
    object_id: str = "",
    actor_type: str = "",
    actor_id: str = "",
    correlation_id: str = "",
    limit: int = 50,
):
    events = AuditEvent.objects.all()
    if action:
        events = events.filter(action=action)
    if object_type:
        events = events.filter(object_type=object_type)
    if object_id:
        events = events.filter(object_id=object_id)
    if actor_type:
        events = events.filter(actor_type=actor_type)
    if actor_id:
        events = events.filter(actor_id=actor_id)
    if correlation_id:
        events = events.filter(correlation_id=correlation_id)
    return events[:limit]


def validate_rule_payload(payload: dict) -> None:
    required_strings = ["rule_id", "name", "owner", "decision"]
    for field in required_strings:
        if not str(payload.get(field, "")).strip():
            raise InvalidRulePayloadError(f"{field} is required.")
    try:
        version = int(payload.get("version", 1))
    except (TypeError, ValueError) as exc:
        raise InvalidRulePayloadError("version must be an integer.") from exc
    if version < 1:
        raise InvalidRulePayloadError("version must be positive.")
    if payload["decision"] not in RuleEvaluation.Decision.values:
        raise InvalidRulePayloadError("decision must be valid.")
    if not isinstance(payload.get("trigger", {}), dict):
        raise InvalidRulePayloadError("trigger must be an object.")
    conditions = payload.get("conditions")
    if not isinstance(conditions, dict):
        raise InvalidRulePayloadError("conditions must be an object.")
    if payload.get("reason_codes", []) is not None and not isinstance(payload.get("reason_codes", []), list):
        raise InvalidRulePayloadError("reason_codes must be a list.")
    evaluate_condition(conditions, {})


def create_rule_proposal(payload: dict, *, actor_id: str, correlation_id: str) -> Rule:
    validate_rule_payload(payload)
    actor = actor_id.strip() or "api"
    with transaction.atomic():
        rule = Rule.objects.create(
            rule_id=str(payload["rule_id"]).strip(),
            version=int(payload.get("version", 1)),
            name=str(payload["name"]).strip(),
            owner=str(payload["owner"]).strip(),
            status=Rule.Status.DRAFT,
            trigger=payload.get("trigger", {}),
            conditions=payload["conditions"],
            decision=payload["decision"],
            reason_codes=payload.get("reason_codes", []),
            schema_version=int(payload.get("schema_version", 1)),
        )
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="governance.rule.proposed",
            object_type="governance.Rule",
            object_id=str(rule.id),
            correlation_id=correlation_id,
            metadata={"rule_id": rule.rule_id, "version": rule.version},
        )
    return rule


def validate_rule(rule_id: str, *, actor_id: str, correlation_id: str) -> Rule:
    actor = actor_id.strip() or "api"
    with transaction.atomic():
        rule = Rule.objects.select_for_update().get(id=rule_id)
        if rule.status not in {Rule.Status.DRAFT, Rule.Status.VALIDATED}:
            raise RuleLifecycleError("Only DRAFT or VALIDATED rules can be validated.")
        validate_rule_payload(
            {
                "rule_id": rule.rule_id,
                "version": rule.version,
                "name": rule.name,
                "owner": rule.owner,
                "trigger": rule.trigger,
                "conditions": rule.conditions,
                "decision": rule.decision,
                "reason_codes": rule.reason_codes,
                "schema_version": rule.schema_version,
            }
        )
        rule.status = Rule.Status.VALIDATED
        rule.save(update_fields=["status"])
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="governance.rule.validated",
            object_type="governance.Rule",
            object_id=str(rule.id),
            correlation_id=correlation_id,
            metadata={"rule_id": rule.rule_id, "version": rule.version},
        )
    return rule


def run_rule_tests(rule_id: str, *, test_cases: list[dict], actor_id: str, correlation_id: str) -> tuple[Rule, list[RuleTestCase]]:
    if not isinstance(test_cases, list) or not test_cases:
        raise InvalidRulePayloadError("test_cases must be a non-empty list.")
    actor = actor_id.strip() or "api"
    created_cases: list[RuleTestCase] = []
    with transaction.atomic():
        rule = Rule.objects.select_for_update().get(id=rule_id)
        if rule.status not in {Rule.Status.VALIDATED, Rule.Status.TESTED}:
            raise RuleLifecycleError("Rule must be VALIDATED before tests run.")
        rule.test_cases.all().delete()
        all_passed = True
        for index, item in enumerate(test_cases):
            if not isinstance(item, dict):
                raise InvalidRulePayloadError("Each test case must be an object.")
            name = str(item.get("name", f"case-{index + 1}")).strip()
            input_event = item.get("input_event")
            expected_decision = item.get("expected_decision")
            expected_match = bool(item.get("expected_match", True))
            if not name:
                raise InvalidRulePayloadError("Test case name cannot be empty.")
            if not isinstance(input_event, dict):
                raise InvalidRulePayloadError("input_event must be an object.")
            if expected_decision not in RuleEvaluation.Decision.values:
                raise InvalidRulePayloadError("expected_decision must be valid.")

            matched, matched_paths = evaluate_condition(rule.conditions, input_event)
            actual_decision = rule.decision if matched else RuleEvaluation.Decision.NEEDS_MORE_DATA
            passed = matched == expected_match and actual_decision == expected_decision
            all_passed = all_passed and passed
            created_cases.append(
                RuleTestCase.objects.create(
                    rule=rule,
                    name=name,
                    input_event=input_event,
                    expected_decision=expected_decision,
                    expected_match=expected_match,
                    passed=passed,
                    actual_decision=actual_decision,
                    matched_paths=matched_paths,
                )
            )

        if not all_passed:
            AuditEvent.objects.create(
                actor_type=AuditEvent.ActorType.SYSTEM,
                actor_id=actor,
                action="governance.rule.test_failed",
                object_type="governance.Rule",
                object_id=str(rule.id),
                correlation_id=correlation_id,
                metadata={"rule_id": rule.rule_id, "version": rule.version, "test_count": len(created_cases)},
            )
            return rule, created_cases

        rule.status = Rule.Status.TESTED
        rule.save(update_fields=["status"])
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="governance.rule.tested",
            object_type="governance.Rule",
            object_id=str(rule.id),
            correlation_id=correlation_id,
            metadata={"rule_id": rule.rule_id, "version": rule.version, "test_count": len(created_cases)},
        )
    return rule, created_cases


def rule_activation_payload(rule: Rule) -> dict:
    return {"rule_id": rule.rule_id, "version": rule.version, "status": Rule.Status.ACTIVE}


def request_rule_activation(rule_id: str, *, requested_by: str, correlation_id: str, expires_at) -> ApprovalRequest:
    actor = requested_by.strip() or "api"
    with transaction.atomic():
        rule = Rule.objects.select_for_update().get(id=rule_id)
        if rule.status != Rule.Status.TESTED:
            raise RuleLifecycleError("Rule must be TESTED before activation can be requested.")
        approval = create_approval_request(
            subject_type="governance.Rule",
            subject_id=str(rule.id),
            subject_version=rule.version,
            action="governance.rule.activate",
            action_payload=rule_activation_payload(rule),
            requested_by=actor,
            correlation_id=correlation_id,
            expires_at=expires_at,
            reason_codes=["RULE_ACTIVATION_REQUIRES_APPROVAL"],
        )
    return approval


def activate_rule(rule_id: str, *, approval_id: str, actor_id: str, correlation_id: str) -> Rule:
    actor = actor_id.strip() or "api"
    with transaction.atomic():
        rule = Rule.objects.select_for_update().get(id=rule_id)
        if rule.status != Rule.Status.TESTED:
            raise RuleLifecycleError("Only TESTED rules can be activated.")

        approval = ApprovalRequest.objects.select_for_update().get(id=approval_id)
        expected_payload = rule_activation_payload(rule)
        if approval.status != ApprovalRequest.Status.APPROVED:
            raise RuleActivationApprovalError("Rule activation requires an APPROVED approval request.")
        if approval.subject_type != "governance.Rule" or approval.subject_id != str(rule.id):
            raise RuleActivationApprovalError("Approval request is not bound to this rule.")
        if approval.subject_version != rule.version:
            raise RuleActivationApprovalError("Approval request is not bound to this rule version.")
        if approval.action != "governance.rule.activate":
            raise RuleActivationApprovalError("Approval request is not for rule activation.")
        if approval.action_payload_hash != canonical_hash(expected_payload):
            raise RuleActivationApprovalError("Approval request payload does not match rule activation payload.")

        rule.status = Rule.Status.ACTIVE
        rule.approved_by = approval.decided_by or actor
        rule.approved_at = timezone.now()
        rule.valid_from = rule.approved_at
        rule.save(update_fields=["status", "approved_by", "approved_at", "valid_from"])

        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="governance.rule.activated",
            object_type="governance.Rule",
            object_id=str(rule.id),
            correlation_id=correlation_id,
            metadata={
                "rule_id": rule.rule_id,
                "version": rule.version,
                "approval_id": str(approval.id),
                "approved_by": rule.approved_by,
            },
        )
    return rule


def enqueue_outbox_message(
    *,
    topic: str,
    payload: dict,
    idempotency_key: str,
    correlation_id: str,
    actor_id: str,
) -> tuple[OutboxMessage, bool]:
    topic = topic.strip()
    idempotency_key = idempotency_key.strip()
    correlation_id = correlation_id.strip()
    actor = actor_id.strip() or "api"
    if not topic or not idempotency_key or not correlation_id:
        raise InvalidOutboxPayloadError("topic, idempotency_key and correlation_id are required.")
    if not isinstance(payload, dict):
        raise InvalidOutboxPayloadError("payload must be an object.")

    payload_hash = canonical_hash(payload)
    with transaction.atomic():
        existing = OutboxMessage.objects.select_for_update().filter(idempotency_key=idempotency_key).first()
        if existing:
            if existing.topic != topic or canonical_hash(existing.payload) != payload_hash:
                raise OutboxIdempotencyConflictError("Outbox idempotency key was already used for a different message.")
            return existing, False

        message = OutboxMessage.objects.create(
            topic=topic,
            payload=payload,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="governance.outbox.enqueued",
            object_type="governance.OutboxMessage",
            object_id=str(message.id),
            correlation_id=correlation_id,
            metadata={"topic": message.topic, "idempotency_key": message.idempotency_key, "payload_hash": payload_hash},
        )
    return message, True


def list_outbox_messages(*, status: str = "", topic: str = "", limit: int = 100):
    messages = OutboxMessage.objects.order_by("-created_at")
    if status:
        messages = messages.filter(status=status)
    if topic:
        messages = messages.filter(topic=topic)
    return messages[:limit]


def mark_outbox_for_retry(message_id: str, *, actor_id: str, correlation_id: str) -> OutboxMessage:
    actor = actor_id.strip() or "api"
    correlation = correlation_id.strip()
    if not correlation:
        raise InvalidOutboxPayloadError("correlation_id is required.")
    with transaction.atomic():
        message = OutboxMessage.objects.select_for_update().get(id=message_id)
        if message.status not in {OutboxMessage.Status.FAILED, OutboxMessage.Status.DEAD_LETTER}:
            raise OutboxRecoveryError("Only FAILED or DEAD_LETTER outbox messages can be marked for retry.")
        previous_status = message.status
        message.status = OutboxMessage.Status.PENDING
        message.next_attempt_at = timezone.now()
        message.save(update_fields=["status", "next_attempt_at", "updated_at"])
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="governance.outbox.retry_requested",
            object_type="governance.OutboxMessage",
            object_id=str(message.id),
            correlation_id=correlation,
            metadata={"from_status": previous_status, "to_status": message.status, "topic": message.topic},
        )
    return message


def mark_outbox_dead_letter(message_id: str, *, actor_id: str, correlation_id: str, reason: str = "") -> OutboxMessage:
    actor = actor_id.strip() or "api"
    correlation = correlation_id.strip()
    if not correlation:
        raise InvalidOutboxPayloadError("correlation_id is required.")
    with transaction.atomic():
        message = OutboxMessage.objects.select_for_update().get(id=message_id)
        if message.status == OutboxMessage.Status.SENT:
            raise OutboxRecoveryError("SENT outbox messages cannot be moved to dead letter.")
        previous_status = message.status
        message.status = OutboxMessage.Status.DEAD_LETTER
        message.next_attempt_at = None
        message.save(update_fields=["status", "next_attempt_at", "updated_at"])
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="governance.outbox.dead_lettered",
            object_type="governance.OutboxMessage",
            object_id=str(message.id),
            correlation_id=correlation,
            metadata={"from_status": previous_status, "to_status": message.status, "topic": message.topic, "reason": reason.strip()},
        )
    return message


def record_inbox_event(
    *,
    source: str,
    external_event_id: str,
    payload: dict,
    correlation_id: str,
    actor_id: str,
) -> tuple[InboxEvent, bool]:
    source = source.strip()
    external_event_id = external_event_id.strip()
    correlation_id = correlation_id.strip()
    actor = actor_id.strip() or "api"
    if not source or not external_event_id or not correlation_id:
        raise InvalidInboxPayloadError("source, external_event_id and correlation_id are required.")
    if not isinstance(payload, dict):
        raise InvalidInboxPayloadError("payload must be an object.")

    with transaction.atomic():
        try:
            event, created = InboxEvent.objects.get_or_create(
                source=source,
                external_event_id=external_event_id,
                defaults={"payload": payload, "correlation_id": correlation_id},
            )
        except IntegrityError:
            event = InboxEvent.objects.get(source=source, external_event_id=external_event_id)
            created = False

        if created:
            AuditEvent.objects.create(
                actor_type=AuditEvent.ActorType.SYSTEM,
                actor_id=actor,
                action="governance.inbox.received",
                object_type="governance.InboxEvent",
                object_id=str(event.id),
                correlation_id=correlation_id,
                metadata={"source": event.source, "external_event_id": event.external_event_id},
            )
    return event, created


def resolve_field(data: dict, field_path: str) -> tuple[bool, Any]:
    current: Any = data
    for part in field_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def evaluate_condition(condition: dict, data: dict, *, path: str = "$") -> tuple[bool, list[str]]:
    if not isinstance(condition, dict):
        raise InvalidRuleConditionError("Condition must be an object.")

    if "all" in condition:
        children = condition["all"]
        if not isinstance(children, list) or not children:
            raise InvalidRuleConditionError("all must contain at least one condition.")
        matched_paths: list[str] = []
        for index, child in enumerate(children):
            matched, child_paths = evaluate_condition(child, data, path=f"{path}.all[{index}]")
            if not matched:
                return False, []
            matched_paths.extend(child_paths)
        return True, matched_paths

    if "any" in condition:
        children = condition["any"]
        if not isinstance(children, list) or not children:
            raise InvalidRuleConditionError("any must contain at least one condition.")
        matched_paths = []
        for index, child in enumerate(children):
            matched, child_paths = evaluate_condition(child, data, path=f"{path}.any[{index}]")
            if matched:
                matched_paths.extend(child_paths)
        return bool(matched_paths), matched_paths

    if "not" in condition:
        matched, _child_paths = evaluate_condition(condition["not"], data, path=f"{path}.not")
        return (not matched), ([path] if not matched else [])

    field = condition.get("field")
    operator = condition.get("operator")
    if not isinstance(field, str) or operator not in ALLOWED_OPERATORS:
        raise InvalidRuleConditionError("Leaf condition requires field and a supported operator.")

    exists, actual = resolve_field(data, field)
    expected = condition.get("value")

    if operator == "exists":
        matched = exists if expected is None else exists == bool(expected)
    elif not exists:
        matched = False
    elif operator == "equals":
        matched = actual == expected
    elif operator == "not_equals":
        matched = actual != expected
    elif operator == "less_than":
        matched = actual < expected
    elif operator == "less_or_equal":
        matched = actual <= expected
    elif operator == "greater_than":
        matched = actual > expected
    elif operator == "greater_or_equal":
        matched = actual >= expected
    elif operator == "in":
        matched = isinstance(expected, list) and actual in expected
    elif operator == "not_in":
        matched = isinstance(expected, list) and actual not in expected
    else:
        raise InvalidRuleConditionError("Unsupported operator.")

    return matched, ([path] if matched else [])


def evaluate_rules(event: dict, *, event_id: str) -> EvaluationResult:
    active_rules = Rule.objects.filter(status=Rule.Status.ACTIVE).order_by("rule_id", "-version")
    input_hash = canonical_hash(event)

    for rule in active_rules:
        matched, matched_paths = evaluate_condition(rule.conditions, event)
        if not matched:
            continue
        evaluation = RuleEvaluation.objects.create(
            event_id=event_id,
            rule=rule,
            decision=rule.decision,
            matched_paths=matched_paths,
            reason_codes=rule.reason_codes,
            input_snapshot_hash=input_hash,
        )
        return EvaluationResult(
            decision=evaluation.decision,
            rule=rule,
            matched_paths=evaluation.matched_paths,
            reason_codes=evaluation.reason_codes,
        )

    evaluation = RuleEvaluation.objects.create(
        event_id=event_id,
        rule=None,
        decision=RuleEvaluation.Decision.NEEDS_MORE_DATA,
        matched_paths=[],
        reason_codes=["NO_MATCHING_ACTIVE_RULE"],
        input_snapshot_hash=input_hash,
    )
    return EvaluationResult(
        decision=evaluation.decision,
        rule=None,
        matched_paths=evaluation.matched_paths,
        reason_codes=evaluation.reason_codes,
    )


def record_rule_event(payload: dict, *, actor_id: str, correlation_id: str) -> RuleEvaluation:
    source = str(payload.get("source", "rules_api")).strip()
    external_event_id = str(payload.get("external_event_id", "")).strip()
    event = payload.get("event", {})
    if not source or not external_event_id:
        raise InvalidRuleEventPayloadError("source and external_event_id are required.")
    if not isinstance(event, dict):
        raise InvalidRuleEventPayloadError("event must be an object.")

    actor = actor_id.strip() or "api"
    event_id = f"{source}:{external_event_id}"
    with transaction.atomic():
        result = evaluate_rules(event, event_id=event_id)
        evaluation = RuleEvaluation.objects.select_related("rule").filter(event_id=event_id).latest("evaluated_at")
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="governance.rule_event.evaluated",
            object_type="governance.RuleEvaluation",
            object_id=str(evaluation.id),
            correlation_id=correlation_id,
            metadata={
                "source": source,
                "external_event_id": external_event_id,
                "decision": result.decision,
                "rule_id": result.rule.rule_id if result.rule else "",
                "reason_codes": result.reason_codes,
            },
        )
    return evaluation


def _rules_engine_module():
    rules_engine_root = Path(settings.BASE_DIR).parent / "rules_engine"
    if not rules_engine_root.exists():
        raise RuleEngineUnavailableError(f"rules_engine project was not found at {rules_engine_root}.")
    root = str(rules_engine_root)
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        return import_module("compass_rules")
    except Exception as exc:
        raise RuleEngineUnavailableError(f"rules_engine could not be loaded: {exc}") from exc


def _as_plain_list(values: list[Any]) -> list[dict]:
    result: list[dict] = []
    for value in values:
        if hasattr(value, "model_dump"):
            result.append(value.model_dump(mode="json"))
        elif isinstance(value, dict):
            result.append(value)
        else:
            result.append({"value": str(value)})
    return result


def _build_rules_engine_event(payload: dict, *, correlation_id: str) -> tuple[str, str, str, dict]:
    source = str(payload.get("source", "sharons")).strip()
    external_event_id = str(payload.get("external_event_id", "")).strip()
    event = payload.get("event", {})
    if not source or not external_event_id:
        raise InvalidRuleEventPayloadError("source and external_event_id are required.")
    if not isinstance(event, dict):
        raise InvalidRuleEventPayloadError("event must be an object.")
    if not str(event.get("event_type", "")).strip():
        raise InvalidRuleEventPayloadError("event.event_type is required.")

    event = {**event}
    metadata = event.get("metadata", {})
    if not isinstance(metadata, dict):
        raise InvalidRuleEventPayloadError("event.metadata must be an object when provided.")
    event["metadata"] = {**metadata, "dry_run": True, "trace_id": metadata.get("trace_id") or correlation_id}
    event["idempotency_key"] = str(event.get("idempotency_key") or f"{source}:{external_event_id}")
    return source, external_event_id, str(event["event_type"]), event


def evaluate_rules_engine_dry_run(payload: dict, *, actor_id: str, correlation_id: str) -> tuple[RuleEngineRun, ApprovalRequest | None]:
    source, external_event_id, event_type, event = _build_rules_engine_event(payload, correlation_id=correlation_id)
    actor = actor_id.strip() or "api"
    compass_rules = _rules_engine_module()

    with transaction.atomic():
        existing = RuleEngineRun.objects.select_for_update().filter(source=source, external_event_id=external_event_id).first()
        if existing:
            approval = ApprovalRequest.objects.filter(subject_type="governance.RuleEngineRun", subject_id=str(existing.id)).first()
            return existing, approval

        try:
            result = compass_rules.evaluate_structured_event(event, dry_run=True)
        except Exception as exc:
            raise InvalidRuleEventPayloadError(str(exc)) from exc

        raw_result = result.model_dump(mode="json")
        run = RuleEngineRun.objects.create(
            source=source,
            external_event_id=external_event_id,
            event_type=event_type,
            event_payload=event,
            dry_run=True,
            final_decision=result.final_decision,
            risk_level=result.risk_level,
            reason_codes=list(result.reason_codes),
            matched_rules=_as_plain_list(list(result.matched_rules)),
            allowed_actions=_as_plain_list(list(result.allowed_actions)),
            approval_required_actions=_as_plain_list(list(result.approval_required_actions)),
            blocked_actions=_as_plain_list(list(result.blocked_actions)),
            routes=_as_plain_list(list(result.routes)),
            raw_result=raw_result,
        )

        approval = None
        if result.final_decision in {"require_approval", "block"} or result.approval_required_actions or result.blocked_actions:
            approval = create_approval_request(
                subject_type="governance.RuleEngineRun",
                subject_id=str(run.id),
                subject_version=1,
                action="governance.rules_engine.review",
                action_payload={
                    "rule_engine_run_id": str(run.id),
                    "source": source,
                    "external_event_id": external_event_id,
                    "event_type": event_type,
                    "final_decision": result.final_decision,
                    "dry_run": True,
                    "prohibited_external_execution": True,
                },
                requested_by=actor,
                correlation_id=correlation_id,
                expires_at=timezone.now() + timezone.timedelta(hours=24),
                reason_codes=list(result.reason_codes),
            )

        if result.allowed_actions:
            AuditEvent.objects.create(
                actor_type=AuditEvent.ActorType.SYSTEM,
                actor_id=actor,
                action="governance.rules_engine.proposals_created",
                object_type="governance.RuleEngineRun",
                object_id=str(run.id),
                correlation_id=correlation_id,
                metadata={
                    "source": source,
                    "external_event_id": external_event_id,
                    "event_type": event_type,
                    "allowed_actions": _as_plain_list(list(result.allowed_actions)),
                    "dry_run": True,
                    "external_action_executed": False,
                },
            )

        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="governance.rules_engine.dry_run_evaluated",
            object_type="governance.RuleEngineRun",
            object_id=str(run.id),
            correlation_id=correlation_id,
            metadata={
                "source": source,
                "external_event_id": external_event_id,
                "event_type": event_type,
                "final_decision": result.final_decision,
                "risk_level": result.risk_level,
                "approval_id": str(approval.id) if approval else "",
                "dry_run": True,
                "external_action_executed": False,
            },
        )
    return run, approval


def create_approval_request(
    *,
    subject_type: str,
    subject_id: str,
    subject_version: int,
    action: str,
    action_payload: dict,
    requested_by: str,
    correlation_id: str,
    expires_at,
    reason_codes: list[str] | None = None,
) -> ApprovalRequest:
    payload_hash = canonical_hash(action_payload)
    requested_by = requested_by.strip() or "api"
    correlation_id = correlation_id.strip()

    with transaction.atomic():
        approval = ApprovalRequest.objects.create(
            subject_type=subject_type,
            subject_id=subject_id,
            subject_version=subject_version,
            action=action,
            action_payload=action_payload,
            action_payload_hash=payload_hash,
            requested_by=requested_by,
            reason_codes=reason_codes or [],
            expires_at=expires_at,
        )
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=requested_by,
            action="governance.approval.requested",
            object_type="governance.ApprovalRequest",
            object_id=str(approval.id),
            correlation_id=correlation_id,
            metadata={
                "subject_type": approval.subject_type,
                "subject_id": approval.subject_id,
                "subject_version": approval.subject_version,
                "approval_action": approval.action,
                "action_payload_hash": approval.action_payload_hash,
            },
        )
    return approval


def decide_approval_request(
    approval_id: str,
    *,
    decision: str,
    actor_id: str,
    subject_version: int,
    action_payload: dict,
    correlation_id: str,
) -> ApprovalRequest:
    if decision not in {ApprovalRequest.Status.APPROVED, ApprovalRequest.Status.REJECTED}:
        raise InvalidApprovalDecisionError("Decision must be APPROVED or REJECTED.")

    actor_id = actor_id.strip() or "api"
    correlation_id = correlation_id.strip()
    payload_hash = canonical_hash(action_payload)
    expired = False

    with transaction.atomic():
        approval = ApprovalRequest.objects.select_for_update().get(id=approval_id)
        if approval.status != ApprovalRequest.Status.PENDING:
            raise ApprovalAlreadyDecidedError("Approval request is no longer pending.")

        now = timezone.now()
        if approval.expires_at <= now:
            approval.status = ApprovalRequest.Status.EXPIRED
            approval.decided_at = now
            approval.save(update_fields=["status", "decided_at"])
            expired = True

        elif approval.subject_version != subject_version:
            raise ApprovalVersionMismatchError("Subject version does not match the approval request.")

        elif approval.action_payload_hash != payload_hash:
            raise ApprovalPayloadMismatchError("Action payload hash does not match the approval request.")

        else:
            approval.status = decision
            approval.decided_by = actor_id
            approval.decided_at = now
            approval.save(update_fields=["status", "decided_by", "decided_at"])

            AuditEvent.objects.create(
                actor_type=AuditEvent.ActorType.HUMAN,
                actor_id=actor_id,
                action="governance.approval.decided",
                object_type="governance.ApprovalRequest",
                object_id=str(approval.id),
                correlation_id=correlation_id,
                metadata={
                    "decision": approval.status,
                    "subject_type": approval.subject_type,
                    "subject_id": approval.subject_id,
                    "subject_version": approval.subject_version,
                    "approval_action": approval.action,
                    "action_payload_hash": approval.action_payload_hash,
                },
            )
    if expired:
        raise ApprovalExpiredError("Approval request has expired.")
    return approval


def route_rule_engine_work_item_owner(item: dict, run: RuleEngineRun) -> str:
    item_type = str(item.get("item_type", "")).strip()
    action_type = str(item.get("action_type", "")).strip().lower()
    component = str(item.get("component", "")).strip().lower()
    purpose = str(item.get("purpose", "")).strip().lower()
    reason_code = str(item.get("reason_code", "")).strip().lower()
    event_type = str(run.event_type).strip().lower()
    searchable_text = " ".join([action_type, component, purpose, reason_code, event_type])

    if component == "owner_review":
        return "chief_of_staff"
    if any(term in searchable_text for term in ["sensitive", "legal", "external_commitment", "human_review"]):
        return "chief_of_staff"
    if component == "sharons_finance" or any(term in searchable_text for term in ["finance", "invoice", "payment"]):
        return "finance_agent"
    if component in {"sharons_files", "sharons_operations"}:
        return "executive_assistant"
    if event_type.startswith("inbound_email") or any(term in searchable_text for term in ["file", "task", "email"]):
        return "executive_assistant"
    if item_type == "ROUTE_REVIEW":
        return "chief_of_staff"
    return "chief_of_staff"


def materialize_rule_engine_review_items(run: RuleEngineRun) -> list[dict]:
    items: list[dict] = []
    for action in run.approval_required_actions:
        items.append(
            {
                "item_type": "APPROVAL_REQUIRED_ACTION",
                "action_type": action.get("action_type", ""),
                "title": action.get("title", ""),
                "component": action.get("component", ""),
                "purpose": action.get("purpose", ""),
                "source_run_id": str(run.id),
                "no_external_action": True,
            }
        )
    for action in run.allowed_actions:
        items.append(
            {
                "item_type": "INTERNAL_PROPOSAL",
                "action_type": action.get("action_type", ""),
                "title": action.get("title", ""),
                "component": action.get("component", ""),
                "purpose": action.get("purpose", ""),
                "source_run_id": str(run.id),
                "no_external_action": True,
            }
        )
    for action in run.blocked_actions:
        items.append(
            {
                "item_type": "BLOCKED_REVIEW",
                "action_type": action.get("action_type", ""),
                "title": action.get("title", ""),
                "reason_code": action.get("reason_code", ""),
                "source_run_id": str(run.id),
                "no_external_action": True,
            }
        )
    for route in run.routes:
        items.append(
            {
                "item_type": "ROUTE_REVIEW",
                "component": route.get("component", ""),
                "capability": route.get("capability", ""),
                "purpose": route.get("purpose", ""),
                "source_run_id": str(run.id),
                "no_external_action": True,
            }
        )
    if not items:
        items.append(
            {
                "item_type": "HUMAN_REVIEW_NOTE",
                "title": f"Review {run.event_type}",
                "source_run_id": str(run.id),
                "no_external_action": True,
            }
        )
    return items


def create_rule_engine_work_items(
    *,
    run: RuleEngineRun,
    execution: ApprovedActionExecution,
    items: list[dict],
    actor_id: str,
    correlation_id: str,
) -> list[RuleEngineWorkItem]:
    created: list[RuleEngineWorkItem] = []
    for item in items:
        owner_agent_id = route_rule_engine_work_item_owner(item, run)
        status = RuleEngineWorkItem.Status.ASSIGNED if owner_agent_id else RuleEngineWorkItem.Status.OPEN
        item_payload = {**item, "routed_owner_agent_id": owner_agent_id, "routed_status": status}
        work_item = RuleEngineWorkItem.objects.create(
            run=run,
            execution=execution,
            item_type=str(item.get("item_type", "")).strip(),
            action_type=str(item.get("action_type", "")).strip(),
            title=str(item.get("title", "")).strip(),
            component=str(item.get("component", "")).strip(),
            purpose=str(item.get("purpose", "")).strip(),
            reason_code=str(item.get("reason_code", "")).strip(),
            payload=item_payload,
            status=status,
            owner_agent_id=owner_agent_id,
            no_external_action=True,
        )
        created.append(work_item)
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor_id,
            action="governance.rules_engine.work_item.created",
            object_type="governance.RuleEngineWorkItem",
            object_id=str(work_item.id),
            correlation_id=correlation_id,
            metadata={
                "rule_engine_run_id": str(run.id),
                "execution_id": str(execution.id),
                "item_type": work_item.item_type,
                "action_type": work_item.action_type,
                "owner_agent_id": work_item.owner_agent_id,
                "status": work_item.status,
                "no_external_action": True,
            },
        )
    return created


def update_rule_engine_work_item(
    item_id: str,
    *,
    status: str = "",
    owner_agent_id: str = "",
    actor_id: str,
    correlation_id: str,
) -> RuleEngineWorkItem:
    if status and status not in RuleEngineWorkItem.Status.values:
        raise InvalidRuleEngineWorkItemUpdateError("status must be valid.")
    actor = actor_id.strip() or "api"
    with transaction.atomic():
        item = RuleEngineWorkItem.objects.select_for_update().get(id=item_id)
        before_status = item.status
        before_owner = item.owner_agent_id
        update_fields = ["updated_at"]
        if status:
            if item.status in {RuleEngineWorkItem.Status.COMPLETED, RuleEngineWorkItem.Status.CANCELLED}:
                raise InvalidRuleEngineWorkItemUpdateError("Completed or cancelled work items cannot be updated.")
            if status == RuleEngineWorkItem.Status.COMPLETED and not item.owner_agent_id and not owner_agent_id:
                raise InvalidRuleEngineWorkItemUpdateError("owner_agent_id is required before completion.")
            item.status = status
            update_fields.append("status")
        if owner_agent_id:
            item.owner_agent_id = owner_agent_id.strip()
            update_fields.append("owner_agent_id")
            if not status and item.status == RuleEngineWorkItem.Status.OPEN:
                item.status = RuleEngineWorkItem.Status.ASSIGNED
                update_fields.append("status")
        item.save(update_fields=list(dict.fromkeys(update_fields)))
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="governance.rules_engine.work_item.updated",
            object_type="governance.RuleEngineWorkItem",
            object_id=str(item.id),
            correlation_id=correlation_id,
            metadata={
                "from_status": before_status,
                "to_status": item.status,
                "from_owner_agent_id": before_owner,
                "to_owner_agent_id": item.owner_agent_id,
                "no_external_action": item.no_external_action,
            },
        )
    return item


def execute_approved_approval(approval_id: str, *, actor_id: str, correlation_id: str) -> ApprovedActionExecution:
    actor = actor_id.strip() or "api"
    correlation = correlation_id.strip()
    if not correlation:
        raise ApprovedActionExecutionError("correlation_id is required.")

    with transaction.atomic():
        approval = ApprovalRequest.objects.select_for_update().get(id=approval_id)
        if approval.status != ApprovalRequest.Status.APPROVED:
            raise ApprovedActionExecutionError("Approval request must be APPROVED before execution.")
        if hasattr(approval, "execution"):
            raise ApprovedActionAlreadyExecutedError("Approved action has already been executed.")

        if approval.action == "governance.rules_engine.review":
            if approval.subject_type != "governance.RuleEngineRun":
                raise ApprovedActionExecutionError("Rule engine review approvals must reference a RuleEngineRun.")
            run = RuleEngineRun.objects.select_for_update().get(id=approval.subject_id)
            items = materialize_rule_engine_review_items(run)
            execution = ApprovedActionExecution.objects.create(
                approval=approval,
                action=approval.action,
                status=ApprovedActionExecution.Status.SUCCEEDED,
                result={
                    "rule_engine_run_id": str(run.id),
                    "event_type": run.event_type,
                    "final_decision": run.final_decision,
                    "reason_codes": run.reason_codes,
                    "created_internal_items": items,
                    "external_action_executed": False,
                },
                executed_by=actor,
                correlation_id=correlation,
            )
            work_items = create_rule_engine_work_items(
                run=run,
                execution=execution,
                items=items,
                actor_id=actor,
                correlation_id=correlation,
            )
            execution.result = {
                **execution.result,
                "created_work_item_ids": [str(item.id) for item in work_items],
            }
            execution.save(update_fields=["result"])
            AuditEvent.objects.create(
                actor_type=AuditEvent.ActorType.SYSTEM,
                actor_id=actor,
                action="governance.rules_engine.review.executed",
                object_type="governance.ApprovedActionExecution",
                object_id=str(execution.id),
                correlation_id=correlation,
                metadata={
                    "approval_id": str(approval.id),
                    "rule_engine_run_id": str(run.id),
                    "item_count": len(items),
                    "work_item_ids": [str(item.id) for item in work_items],
                    "external_action_executed": False,
                },
            )
            AuditEvent.objects.create(
                actor_type=AuditEvent.ActorType.SYSTEM,
                actor_id=actor,
                action="governance.approval.executed",
                object_type="governance.ApprovedActionExecution",
                object_id=str(execution.id),
                correlation_id=correlation,
                metadata={"approval_id": str(approval.id), "executed_action": approval.action, "rule_engine_run_id": str(run.id)},
            )
            return execution

        if approval.action != "operations.task.transition":
            execution = ApprovedActionExecution.objects.create(
                approval=approval,
                action=approval.action,
                status=ApprovedActionExecution.Status.FAILED,
                error_code=UnsupportedApprovedActionError.code,
                error_message=f"Unsupported approved action: {approval.action}",
                executed_by=actor,
                correlation_id=correlation,
            )
            AuditEvent.objects.create(
                actor_type=AuditEvent.ActorType.SYSTEM,
                actor_id=actor,
                action="governance.approval.execution_failed",
                object_type="governance.ApprovedActionExecution",
                object_id=str(execution.id),
                correlation_id=correlation,
                metadata={"approval_id": str(approval.id), "executed_action": approval.action, "error_code": execution.error_code},
            )
            raise UnsupportedApprovedActionError(execution.error_message)

        from operations.services import transition_task

        task = transition_task(
            str(approval.subject_id),
            to_status=str(approval.action_payload["to_status"]),
            expected_version=int(approval.action_payload["expected_version"]),
            actor_id=actor,
            correlation_id=correlation,
        )
        execution = ApprovedActionExecution.objects.create(
            approval=approval,
            action=approval.action,
            status=ApprovedActionExecution.Status.SUCCEEDED,
            result={"task_id": str(task.id), "task_status": task.status, "task_version": task.version},
            executed_by=actor,
            correlation_id=correlation,
        )
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="governance.approval.executed",
            object_type="governance.ApprovedActionExecution",
            object_id=str(execution.id),
            correlation_id=correlation,
            metadata={"approval_id": str(approval.id), "executed_action": approval.action, "task_id": str(task.id), "task_status": task.status},
        )
    return execution
