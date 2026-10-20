import json

from django.contrib import messages
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.models import IdempotencyRecord
from core.services import canonical_hash
from governance.forms import ApprovalDecisionForm, approval_decision_initial
from governance.models import ApprovalRequest, AuditEvent, OutboxMessage, RuleEngineRun, RuleEngineWorkItem
from governance.services import (
    ApprovalError,
    ApprovalExpiredError,
    ApprovalPayloadMismatchError,
    ApprovalVersionMismatchError,
    ApprovedActionAlreadyExecutedError,
    ApprovedActionExecutionError,
    InvalidRuleEngineWorkItemUpdateError,
    UnsupportedApprovedActionError,
    InvalidApprovalDecisionError,
    InvalidRuleConditionError,
    InvalidRuleEventPayloadError,
    InvalidRulePayloadError,
    InvalidOutboxPayloadError,
    OutboxRecoveryError,
    RuleEngineUnavailableError,
    RuleActivationApprovalError,
    RuleLifecycleError,
    activate_rule,
    create_rule_proposal,
    decide_approval_request,
    evaluate_rules_engine_dry_run,
    execute_approved_approval,
    record_rule_event,
    run_rule_tests,
    search_audit_events,
    list_rule_engine_runs,
    list_rule_engine_work_items,
    list_outbox_messages,
    mark_outbox_dead_letter,
    mark_outbox_for_retry,
    serialize_audit_event,
    serialize_approval_request,
    serialize_approved_action_execution,
    serialize_outbox_message,
    serialize_rule,
    serialize_rule_engine_run,
    serialize_rule_engine_work_item,
    serialize_rule_evaluation,
    serialize_rule_test_case,
    validate_rule,
    request_rule_activation,
    update_rule_engine_work_item,
)


def error_response(code: str, message: str, status: int) -> JsonResponse:
    return JsonResponse({"error": {"code": code, "message": message}}, status=status)


class ApprovalPayloadError(ApprovalError):
    code = "INVALID_APPROVAL_PAYLOAD"


def require_change_headers(request) -> tuple[str, str, str]:
    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    correlation_id = request.headers.get("X-Correlation-ID", "").strip()
    actor_id = request.headers.get("X-Actor-ID", "api").strip() or "api"
    if not idempotency_key or not correlation_id:
        raise ApprovalPayloadError("Idempotency-Key and X-Correlation-ID are required.")
    return idempotency_key, correlation_id, actor_id


def dashboard_actor_id(request) -> str:
    if request.user.is_authenticated:
        return str(request.user.get_username())
    return "dashboard"


@require_GET
def approvals_list(request):
    status = request.GET.get("status", "").strip()
    approvals = ApprovalRequest.objects.all()
    if status:
        if status not in ApprovalRequest.Status.values:
            return error_response("INVALID_APPROVAL_STATUS", "status must be a valid approval status.", 400)
        approvals = approvals.filter(status=status)
    return JsonResponse({"approvals": [serialize_approval_request(approval) for approval in approvals]})


@require_GET
def audit_list(request):
    action = request.GET.get("action", "").strip()
    object_type = request.GET.get("object_type", "").strip()
    object_id = request.GET.get("object_id", "").strip()
    actor_type = request.GET.get("actor_type", "").strip()
    actor_id = request.GET.get("actor_id", "").strip()
    correlation_id = request.GET.get("correlation_id", "").strip()
    limit_raw = request.GET.get("limit", "50").strip()

    if actor_type and actor_type not in AuditEvent.ActorType.values:
        return error_response("INVALID_AUDIT_FILTER", "actor_type must be valid.", 400)
    try:
        limit = int(limit_raw)
    except ValueError:
        return error_response("INVALID_AUDIT_FILTER", "limit must be an integer.", 400)
    if limit < 1 or limit > 100:
        return error_response("INVALID_AUDIT_FILTER", "limit must be between 1 and 100.", 400)

    events = search_audit_events(
        action=action,
        object_type=object_type,
        object_id=object_id,
        actor_type=actor_type,
        actor_id=actor_id,
        correlation_id=correlation_id,
        limit=limit,
    )
    return JsonResponse({"audit_events": [serialize_audit_event(event) for event in events]})


@login_required
@require_GET
def outbox_dashboard(request):
    status = request.GET.get("status", "").strip()
    topic = request.GET.get("topic", "").strip()
    if status and status not in OutboxMessage.Status.values:
        status = ""
    return render(
        request,
        "governance/outbox_dashboard.html",
        {
            "messages": list_outbox_messages(status=status, topic=topic),
            "statuses": OutboxMessage.Status.values,
            "selected_status": status,
            "topic": topic,
        },
    )


@require_GET
def outbox_list(request):
    status = request.GET.get("status", "").strip()
    topic = request.GET.get("topic", "").strip()
    limit_raw = request.GET.get("limit", "100").strip()
    if status and status not in OutboxMessage.Status.values:
        return error_response("INVALID_OUTBOX_FILTER", "status must be valid.", 400)
    try:
        limit = int(limit_raw)
    except ValueError:
        return error_response("INVALID_OUTBOX_FILTER", "limit must be an integer.", 400)
    if limit < 1 or limit > 200:
        return error_response("INVALID_OUTBOX_FILTER", "limit must be between 1 and 200.", 400)
    messages = list_outbox_messages(status=status, topic=topic, limit=limit)
    return JsonResponse({"outbox_messages": [serialize_outbox_message(message) for message in messages]})


@login_required
@require_http_methods(["GET", "POST"])
def rules_engine_dashboard(request):
    if request.method == "POST":
        item_id = request.POST.get("item_id", "").strip()
        status = request.POST.get("status", "").strip()
        owner_agent_id = request.POST.get("owner_agent_id", "").strip()
        try:
            update_rule_engine_work_item(
                item_id,
                status=status,
                owner_agent_id=owner_agent_id,
                actor_id=dashboard_actor_id(request),
                correlation_id=f"dashboard-rule-work-item-{item_id}",
            )
            messages.success(request, "Work item updated.")
        except (RuleEngineWorkItem.DoesNotExist, InvalidRuleEngineWorkItemUpdateError) as exc:
            messages.error(request, str(exc))
        return redirect("rules-engine-dashboard")

    source = request.GET.get("source", "").strip()
    event_type = request.GET.get("event_type", "").strip()
    final_decision = request.GET.get("final_decision", "").strip()
    work_status = request.GET.get("work_status", "").strip()
    return render(
        request,
        "governance/rules_engine_dashboard.html",
        {
            "runs": list_rule_engine_runs(source=source, event_type=event_type, final_decision=final_decision, limit=100),
            "work_items": list_rule_engine_work_items(status=work_status, limit=100),
            "work_item_statuses": RuleEngineWorkItem.Status.values,
            "source": source,
            "event_type": event_type,
            "final_decision": final_decision,
            "work_status": work_status,
        },
    )


@require_GET
def rules_engine_runs_list(request):
    source = request.GET.get("source", "").strip()
    event_type = request.GET.get("event_type", "").strip()
    final_decision = request.GET.get("final_decision", "").strip()
    limit_raw = request.GET.get("limit", "100").strip()
    try:
        limit = int(limit_raw)
    except ValueError:
        return error_response("INVALID_RULE_ENGINE_RUN_FILTER", "limit must be an integer.", 400)
    if limit < 1 or limit > 200:
        return error_response("INVALID_RULE_ENGINE_RUN_FILTER", "limit must be between 1 and 200.", 400)
    runs = list_rule_engine_runs(source=source, event_type=event_type, final_decision=final_decision, limit=limit)
    return JsonResponse({"runs": [serialize_rule_engine_run(run) for run in runs]})


@require_GET
def rules_engine_run_detail(request, run_id):
    try:
        run = RuleEngineRun.objects.get(id=run_id)
    except RuleEngineRun.DoesNotExist:
        return error_response("RULE_ENGINE_RUN_NOT_FOUND", "Rule engine run was not found.", 404)
    return JsonResponse({"run": serialize_rule_engine_run(run, include_raw=True)})


@require_GET
def rules_engine_work_items_list(request):
    status = request.GET.get("status", "").strip()
    owner_agent_id = request.GET.get("owner_agent_id", "").strip()
    item_type = request.GET.get("item_type", "").strip()
    limit_raw = request.GET.get("limit", "100").strip()
    try:
        limit = int(limit_raw)
    except ValueError:
        return error_response("INVALID_RULE_ENGINE_WORK_ITEM_FILTER", "limit must be an integer.", 400)
    if limit < 1 or limit > 200:
        return error_response("INVALID_RULE_ENGINE_WORK_ITEM_FILTER", "limit must be between 1 and 200.", 400)
    items = list_rule_engine_work_items(status=status, owner_agent_id=owner_agent_id, item_type=item_type, limit=limit)
    return JsonResponse({"work_items": [serialize_rule_engine_work_item(item) for item in items]})


@csrf_exempt
@require_POST
def rules_engine_work_item_update(request, item_id):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        if not isinstance(payload, dict):
            raise ApprovalPayloadError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = require_change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        item = update_rule_engine_work_item(
            str(item_id),
            status=str(payload.get("status", "")).strip(),
            owner_agent_id=str(payload.get("owner_agent_id", "")).strip(),
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        response = {"work_item": serialize_rule_engine_work_item(item), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=200)
        return JsonResponse(response, status=200)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except ApprovalPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except InvalidRuleEngineWorkItemUpdateError as exc:
        return error_response(exc.code, str(exc), 409)
    except Exception as exc:
        if exc.__class__.__name__ == "DoesNotExist":
            return error_response("RULE_ENGINE_WORK_ITEM_NOT_FOUND", "Rule engine work item was not found.", 404)
        raise


@csrf_exempt
@require_POST
def outbox_retry(request, message_id):
    try:
        idempotency_key, correlation_id, actor_id = require_change_headers(request)
        payload = {"message_id": str(message_id), "action": "retry"}
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        message = mark_outbox_for_retry(str(message_id), actor_id=actor_id, correlation_id=correlation_id)
        response = {"outbox_message": serialize_outbox_message(message), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=200)
        return JsonResponse(response, status=200)
    except OutboxMessage.DoesNotExist:
        return error_response("OUTBOX_MESSAGE_NOT_FOUND", "Outbox message was not found.", 404)
    except (InvalidOutboxPayloadError, ApprovalPayloadError) as exc:
        return error_response(exc.code, str(exc), 400)
    except OutboxRecoveryError as exc:
        return error_response(exc.code, str(exc), 409)


@csrf_exempt
@require_POST
def outbox_dead_letter(request, message_id):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        if not isinstance(payload, dict):
            raise ApprovalPayloadError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = require_change_headers(request)
        action_payload = {"message_id": str(message_id), "action": "dead_letter", "reason": str(payload.get("reason", "")).strip()}
        request_hash = canonical_hash({"path": request.path, "payload": action_payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        message = mark_outbox_dead_letter(
            str(message_id),
            actor_id=actor_id,
            correlation_id=correlation_id,
            reason=action_payload["reason"],
        )
        response = {"outbox_message": serialize_outbox_message(message), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=200)
        return JsonResponse(response, status=200)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except OutboxMessage.DoesNotExist:
        return error_response("OUTBOX_MESSAGE_NOT_FOUND", "Outbox message was not found.", 404)
    except (InvalidOutboxPayloadError, ApprovalPayloadError) as exc:
        return error_response(exc.code, str(exc), 400)
    except OutboxRecoveryError as exc:
        return error_response(exc.code, str(exc), 409)


@csrf_exempt
@require_POST
def rule_proposal(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ApprovalPayloadError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = require_change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        rule = create_rule_proposal(payload, actor_id=actor_id, correlation_id=correlation_id)
        response = {"rule": serialize_rule(rule), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=201)
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except InvalidRuleConditionError as exc:
        return error_response(exc.code, str(exc), 400)
    except InvalidRulePayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ApprovalPayloadError as exc:
        return error_response(exc.code, str(exc), 400)


@csrf_exempt
@require_POST
def rule_event(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidRuleEventPayloadError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = require_change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        evaluation = record_rule_event(payload, actor_id=actor_id, correlation_id=correlation_id)
        response = {"evaluation": serialize_rule_evaluation(evaluation), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=201)
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except InvalidRuleConditionError as exc:
        return error_response(exc.code, str(exc), 400)
    except InvalidRuleEventPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ApprovalPayloadError as exc:
        return error_response(exc.code, str(exc), 400)


@csrf_exempt
@require_POST
def rules_engine_dry_run(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidRuleEventPayloadError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = require_change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        run, approval = evaluate_rules_engine_dry_run(payload, actor_id=actor_id, correlation_id=correlation_id)
        response = {
            "run": serialize_rule_engine_run(run),
            "approval": serialize_approval_request(approval) if approval else None,
            "correlation_id": correlation_id,
        }
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=201)
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except RuleEngineUnavailableError as exc:
        return error_response(exc.code, str(exc), 503)
    except InvalidRuleEventPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ApprovalPayloadError as exc:
        return error_response(exc.code, str(exc), 400)


@csrf_exempt
@require_POST
def rule_validate(request, rule_id):
    try:
        idempotency_key, correlation_id, actor_id = require_change_headers(request)
        payload = {"rule_id": str(rule_id)}
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        rule = validate_rule(str(rule_id), actor_id=actor_id, correlation_id=correlation_id)
        response = {"rule": serialize_rule(rule), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=200)
        return JsonResponse(response, status=200)
    except RuleLifecycleError as exc:
        return error_response(exc.code, str(exc), 409)
    except InvalidRuleConditionError as exc:
        return error_response(exc.code, str(exc), 400)
    except InvalidRulePayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except Exception as exc:
        if exc.__class__.__name__ == "DoesNotExist":
            return error_response("RULE_NOT_FOUND", "Rule was not found.", 404)
        raise


@csrf_exempt
@require_POST
def rule_test(request, rule_id):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ApprovalPayloadError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = require_change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        rule, test_cases = run_rule_tests(
            str(rule_id),
            test_cases=payload.get("test_cases", []),
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        all_passed = all(test_case.passed for test_case in test_cases)
        response = {
            "rule": serialize_rule(rule),
            "all_passed": all_passed,
            "test_cases": [serialize_rule_test_case(test_case) for test_case in test_cases],
            "correlation_id": correlation_id,
        }
        status_code = 200 if all_passed else 409
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=status_code)
        return JsonResponse(response, status=status_code)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except RuleLifecycleError as exc:
        return error_response(exc.code, str(exc), 409)
    except InvalidRuleConditionError as exc:
        return error_response(exc.code, str(exc), 400)
    except InvalidRulePayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ApprovalPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except Exception as exc:
        if exc.__class__.__name__ == "DoesNotExist":
            return error_response("RULE_NOT_FOUND", "Rule was not found.", 404)
        raise


@csrf_exempt
@require_POST
def rule_activation_request(request, rule_id):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        if not isinstance(payload, dict):
            raise ApprovalPayloadError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = require_change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        expires_hours = int(payload.get("expires_hours", 24))
        if expires_hours < 1 or expires_hours > 168:
            raise ApprovalPayloadError("expires_hours must be between 1 and 168.")
        approval = request_rule_activation(
            str(rule_id),
            requested_by=actor_id,
            correlation_id=correlation_id,
            expires_at=timezone.now() + timezone.timedelta(hours=expires_hours),
        )
        response = {"approval": serialize_approval_request(approval), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=201)
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except (ValueError, ApprovalPayloadError) as exc:
        return error_response(getattr(exc, "code", "INVALID_APPROVAL_PAYLOAD"), str(exc), 400)
    except RuleLifecycleError as exc:
        return error_response(exc.code, str(exc), 409)
    except Exception as exc:
        if exc.__class__.__name__ == "DoesNotExist":
            return error_response("RULE_NOT_FOUND", "Rule was not found.", 404)
        raise


@csrf_exempt
@require_POST
def rule_activate(request, rule_id):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ApprovalPayloadError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = require_change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        approval_id = str(payload.get("approval_id", "")).strip()
        if not approval_id:
            raise ApprovalPayloadError("approval_id is required.")
        rule = activate_rule(str(rule_id), approval_id=approval_id, actor_id=actor_id, correlation_id=correlation_id)
        response = {"rule": serialize_rule(rule), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=200)
        return JsonResponse(response, status=200)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except ApprovalPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except RuleActivationApprovalError as exc:
        return error_response(exc.code, str(exc), 409)
    except RuleLifecycleError as exc:
        return error_response(exc.code, str(exc), 409)
    except Exception as exc:
        if exc.__class__.__name__ == "DoesNotExist":
            return error_response("RULE_OR_APPROVAL_NOT_FOUND", "Rule or approval was not found.", 404)
        raise


@login_required
@permission_required("governance.view_approvalrequest", raise_exception=True)
@require_GET
def approval_inbox(request):
    status = request.GET.get("status", ApprovalRequest.Status.PENDING).strip()
    approvals = ApprovalRequest.objects.all()
    if status:
        if status not in ApprovalRequest.Status.values:
            status = ApprovalRequest.Status.PENDING
        approvals = approvals.filter(status=status)
    return render(
        request,
        "governance/approval_inbox.html",
        {
            "approvals": approvals,
            "selected_status": status,
            "statuses": ApprovalRequest.Status.values,
        },
    )


@login_required
@permission_required("governance.view_approvalrequest", raise_exception=True)
@require_http_methods(["GET", "POST"])
def approval_detail(request, approval_id):
    approval = get_object_or_404(ApprovalRequest, id=approval_id)
    if request.method == "GET":
        return render(
            request,
            "governance/approval_detail.html",
            {
                "approval": approval,
                "form": ApprovalDecisionForm(initial=approval_decision_initial(approval)),
                "error": "",
            },
        )

    form = ApprovalDecisionForm(request.POST)
    if not form.is_valid():
        return render(request, "governance/approval_detail.html", {"approval": approval, "form": form, "error": ""}, status=400)

    if not request.user.has_perm("governance.decide_approvalrequest"):
        return render(
            request,
            "governance/approval_detail.html",
            {"approval": approval, "form": form, "error": "You do not have permission to decide approval requests."},
            status=403,
        )

    try:
        decide_approval_request(
            str(approval.id),
            decision=form.cleaned_data["decision"],
            actor_id=dashboard_actor_id(request),
            subject_version=form.cleaned_data["subject_version"],
            action_payload=form.cleaned_data["action_payload"],
            correlation_id=f"dashboard-approval-{approval.id}",
        )
    except ApprovalError as exc:
        return render(
            request,
            "governance/approval_detail.html",
            {"approval": approval, "form": form, "error": str(exc)},
            status=409,
        )
    return redirect("approval-detail", approval_id=approval.id)


@csrf_exempt
@require_POST
def approval_decision(request, approval_id):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ApprovalPayloadError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = require_change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        decision = str(payload.get("decision", "")).strip()
        try:
            subject_version = int(payload["subject_version"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ApprovalPayloadError("subject_version is required and must be an integer.") from exc
        action_payload = payload.get("action_payload")
        if not isinstance(action_payload, dict):
            raise ApprovalPayloadError("action_payload is required and must be a JSON object.")

        approval = decide_approval_request(
            str(approval_id),
            decision=decision,
            actor_id=actor_id,
            subject_version=subject_version,
            action_payload=action_payload,
            correlation_id=correlation_id,
        )
        response = {"approval": serialize_approval_request(approval), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(
            key=idempotency_key,
            request_hash=request_hash,
            response_payload=response,
            status_code=200,
        )
        return JsonResponse(response, status=200)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except ApprovalRequest.DoesNotExist:
        return error_response("APPROVAL_NOT_FOUND", "Approval request was not found.", 404)
    except (ApprovalVersionMismatchError, ApprovalPayloadMismatchError, ApprovalExpiredError) as exc:
        return error_response(exc.code, str(exc), 409)
    except InvalidApprovalDecisionError as exc:
        return error_response(exc.code, str(exc), 400)
    except ApprovalPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ApprovalError as exc:
        return error_response(exc.code, str(exc), 409)


@csrf_exempt
@require_POST
def approval_execute(request, approval_id):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        if not isinstance(payload, dict):
            raise ApprovalPayloadError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = require_change_headers(request)
        request_payload = {"approval_id": str(approval_id), "payload": payload}
        request_hash = canonical_hash({"path": request.path, "payload": request_payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        execution = execute_approved_approval(str(approval_id), actor_id=actor_id, correlation_id=correlation_id)
        response = {"execution": serialize_approved_action_execution(execution), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=200)
        return JsonResponse(response, status=200)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except ApprovalRequest.DoesNotExist:
        return error_response("APPROVAL_NOT_FOUND", "Approval request was not found.", 404)
    except ApprovalPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except (ApprovedActionAlreadyExecutedError, ApprovedActionExecutionError, UnsupportedApprovedActionError) as exc:
        return error_response(exc.code, str(exc), 409)
