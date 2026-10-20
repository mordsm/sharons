import json

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.models import IdempotencyRecord, MemoryRecord
from core.services import (
    CockpitActionError,
    CosPlanningError,
    IntakeError,
    ConversationFinalizeError,
    EventRecordError,
    InvalidConversationPayloadError,
    InvalidCosPlanningPayloadError,
    InvalidEventPayloadError,
    InvalidMemoryPayloadError,
    InvalidPayloadError,
    MemoryError,
    canonical_hash,
    create_next_developer_plan_from_cockpit,
    create_next_execution_review_from_cockpit,
    create_next_executive_brief_from_cockpit,
    create_next_product_draft_from_cockpit,
    create_next_qa_review_from_cockpit,
    create_memory_record,
    executive_overview,
    finalize_conversation,
    intake_request,
    objective_health_report,
    objective_operating_dashboard,
    objective_operating_review,
    open_next_finance_review_from_cockpit,
    propose_next_actions_for_objective,
    propose_work_for_objective,
    record_internal_event,
    search_memory_records,
    serialize_memory_record,
    serialize_objective_health,
    serialize_objective_operating_dashboard,
    serialize_objective_operating_review,
    serialize_weekly_review,
    serialize_task_summary,
    weekly_review,
)
from governance.models import RuleEngineWorkItem
from governance.services import InvalidRuleEngineWorkItemUpdateError, serialize_audit_event, update_rule_engine_work_item
from core.cos_engine import (
    CeoDecisionBundleEngine,
    CosEngineError,
    CriticalPathEngine,
    DependencyCycleError,
    RiskNotFoundError,
    RiskRegisterEngine,
    WipAndStaleControlEngine,
)


@login_required
@require_http_methods(["GET", "POST"])
def executive_dashboard(request):
    if request.method == "POST":
        try:
            action = request.POST.get("action", "").strip()
            if action == "complete_rule_engine_work_item":
                item_id = request.POST.get("item_id", "").strip()
                item = RuleEngineWorkItem.objects.get(id=item_id, owner_agent_id="chief_of_staff")
                update_rule_engine_work_item(
                    str(item.id),
                    status=RuleEngineWorkItem.Status.COMPLETED,
                    actor_id=request.user.get_username() or "chief_of_staff_dashboard",
                    correlation_id=f"dashboard-chief-rule-work-item-{item.id}",
                )
                messages.success(request, "Rule-engine work item completed.")
            elif action == "create_next_product_draft":
                draft = create_next_product_draft_from_cockpit(
                    actor_id=request.user.get_username() or "chief_of_staff_dashboard",
                    correlation_id="dashboard-cockpit-product-draft",
                )
                messages.success(request, f"Product draft created: {draft.title}")
            elif action == "create_next_developer_plan":
                plan = create_next_developer_plan_from_cockpit(
                    actor_id=request.user.get_username() or "chief_of_staff_dashboard",
                    correlation_id="dashboard-cockpit-developer-plan",
                )
                messages.success(request, f"Developer plan created: {plan.title}")
            elif action == "create_next_execution_review":
                review = create_next_execution_review_from_cockpit(
                    actor_id=request.user.get_username() or "chief_of_staff_dashboard",
                    correlation_id="dashboard-cockpit-execution-review",
                )
                messages.success(request, f"Execution review created: {review.summary}")
            elif action == "create_next_qa_review":
                review = create_next_qa_review_from_cockpit(
                    actor_id=request.user.get_username() or "chief_of_staff_dashboard",
                    correlation_id="dashboard-cockpit-qa-review",
                )
                messages.success(request, f"QA review created: {review.decision}")
            elif action == "create_next_executive_brief":
                brief = create_next_executive_brief_from_cockpit(
                    actor_id=request.user.get_username() or "chief_of_staff_dashboard",
                    correlation_id="dashboard-cockpit-executive-brief",
                )
                messages.success(request, f"Executive brief created: {brief.title}")
            elif action == "open_next_finance_review":
                record = open_next_finance_review_from_cockpit(
                    actor_id=request.user.get_username() or "chief_of_staff_dashboard",
                    correlation_id="dashboard-cockpit-finance-review",
                )
                messages.success(request, f"Finance review opened: {record.description}")
            else:
                raise ValueError("Unknown executive dashboard action.")
        except (RuleEngineWorkItem.DoesNotExist, InvalidRuleEngineWorkItemUpdateError, CockpitActionError, ValueError) as exc:
            messages.error(request, str(exc))
        return redirect("executive-dashboard")
    return render(request, "core/executive_dashboard.html", executive_overview())


@login_required
@require_GET
def weekly_review_page(request):
    return render(request, "core/weekly_review.html", weekly_review())


@require_GET
def weekly_review_api(request):
    return JsonResponse({"weekly_review": serialize_weekly_review(weekly_review())})


@csrf_exempt
@require_POST
def cos_intake(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidPayloadError("Request body must be a JSON object.")
        response, status_code = intake_request(
            payload,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
            correlation_id=request.headers.get("X-Correlation-ID", ""),
            actor_id=request.headers.get("X-Actor-ID", "api"),
        )
        return JsonResponse(response, status=status_code)
    except json.JSONDecodeError:
        return JsonResponse({"error": {"code": "INVALID_JSON", "message": "Request body must be valid JSON."}}, status=400)
    except IntakeError as exc:
        return JsonResponse({"error": {"code": exc.code, "message": str(exc)}}, status=exc.status_code)


@csrf_exempt
@require_POST
def cos_objective_work_propose(request, objective_id):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidCosPlanningPayloadError("Request body must be a JSON object.")
        context, existing = idempotent_mutation(request, payload, InvalidCosPlanningPayloadError)
        if existing:
            return existing
        idempotency_key, correlation_id, actor_id, request_hash = context
        tasks = propose_work_for_objective(payload, objective_id=str(objective_id), actor_id=actor_id, correlation_id=correlation_id)
        response = {
            "tasks": [serialize_task_summary(task) for task in tasks],
            "correlation_id": correlation_id,
            "no_external_action": True,
        }
        IdempotencyRecord.objects.create(
            key=idempotency_key,
            request_hash=request_hash,
            response_payload=response,
            status_code=201,
        )
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return JsonResponse({"error": {"code": "INVALID_JSON", "message": "Request body must be valid JSON."}}, status=400)
    except CosPlanningError as exc:
        return JsonResponse({"error": {"code": exc.code, "message": str(exc)}}, status=exc.status_code)


@require_GET
def cos_objectives_health(request):
    return JsonResponse({"objectives": [serialize_objective_health(health) for health in objective_health_report()]})


@require_GET
def cos_operating_dashboard(request):
    dashboard = objective_operating_dashboard()
    if request.GET.get("format", "").strip().lower() == "json":
        return JsonResponse({"operating_dashboard": serialize_objective_operating_dashboard(dashboard)})
    return render(request, "core/cos_operating_dashboard.html", dashboard)


@require_GET
def cos_objective_operating_review(request, objective_id):
    try:
        review = objective_operating_review(objective_id=str(objective_id))
        return JsonResponse({"operating_review": serialize_objective_operating_review(review)})
    except CosPlanningError as exc:
        return JsonResponse({"error": {"code": exc.code, "message": str(exc)}}, status=exc.status_code)


@csrf_exempt
@require_POST
def cos_objective_next_actions_propose(request, objective_id):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidCosPlanningPayloadError("Request body must be a JSON object.")
        context, existing = idempotent_mutation(request, payload, InvalidCosPlanningPayloadError)
        if existing:
            return existing
        idempotency_key, correlation_id, actor_id, request_hash = context
        tasks = propose_next_actions_for_objective(payload, objective_id=str(objective_id), actor_id=actor_id, correlation_id=correlation_id)
        response = {
            "tasks": [serialize_task_summary(task) for task in tasks],
            "correlation_id": correlation_id,
            "no_external_action": True,
        }
        IdempotencyRecord.objects.create(
            key=idempotency_key,
            request_hash=request_hash,
            response_payload=response,
            status_code=201,
        )
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return JsonResponse({"error": {"code": "INVALID_JSON", "message": "Request body must be valid JSON."}}, status=400)
    except ValueError:
        return JsonResponse({"error": {"code": "INVALID_COS_PLANNING_PAYLOAD", "message": "limit must be an integer."}}, status=400)
    except CosPlanningError as exc:
        return JsonResponse({"error": {"code": exc.code, "message": str(exc)}}, status=exc.status_code)


def change_headers(request, error_cls):
    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    correlation_id = request.headers.get("X-Correlation-ID", "").strip()
    actor_id = request.headers.get("X-Actor-ID", "api").strip() or "api"
    if not idempotency_key or not correlation_id:
        raise error_cls("Idempotency-Key and X-Correlation-ID are required.")
    return idempotency_key, correlation_id, actor_id


def idempotent_mutation(request, payload: dict, error_cls):
    idempotency_key, correlation_id, actor_id = change_headers(request, error_cls)
    request_hash = canonical_hash({"path": request.path, "payload": payload})
    existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
    if existing:
        if existing.request_hash != request_hash:
            return None, JsonResponse(
                {"error": {"code": "IDEMPOTENCY_CONFLICT", "message": "Idempotency key was already used for a different request."}},
                status=409,
            )
        return None, JsonResponse(existing.response_payload, status=existing.status_code)
    return (idempotency_key, correlation_id, actor_id, request_hash), None


@csrf_exempt
@require_POST
def event_create(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidEventPayloadError("Request body must be a JSON object.")
        context, existing = idempotent_mutation(request, payload, InvalidEventPayloadError)
        if existing:
            return existing
        idempotency_key, correlation_id, actor_id, request_hash = context
        event = record_internal_event(payload, actor_id=actor_id, correlation_id=correlation_id)
        response = {"event": serialize_audit_event(event), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=201)
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return JsonResponse({"error": {"code": "INVALID_JSON", "message": "Request body must be valid JSON."}}, status=400)
    except EventRecordError as exc:
        return JsonResponse({"error": {"code": exc.code, "message": str(exc)}}, status=exc.status_code)


@csrf_exempt
@require_POST
def conversation_finalize(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidConversationPayloadError("Request body must be a JSON object.")
        context, existing = idempotent_mutation(request, payload, InvalidConversationPayloadError)
        if existing:
            return existing
        idempotency_key, correlation_id, actor_id, request_hash = context
        record = finalize_conversation(payload, actor_id=actor_id, correlation_id=correlation_id)
        response = {"memory": serialize_memory_record(record), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=201)
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return JsonResponse({"error": {"code": "INVALID_JSON", "message": "Request body must be valid JSON."}}, status=400)
    except ConversationFinalizeError as exc:
        return JsonResponse({"error": {"code": exc.code, "message": str(exc)}}, status=exc.status_code)


@csrf_exempt
@require_POST
def memory_create(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidMemoryPayloadError("Request body must be a JSON object.")
        idempotency_key = request.headers.get("Idempotency-Key", "").strip()
        correlation_id = request.headers.get("X-Correlation-ID", "").strip()
        actor_id = request.headers.get("X-Actor-ID", "api").strip() or "api"
        if not idempotency_key or not correlation_id:
            raise InvalidMemoryPayloadError("Idempotency-Key and X-Correlation-ID are required.")

        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return JsonResponse(
                    {"error": {"code": "IDEMPOTENCY_CONFLICT", "message": "Idempotency key was already used for a different request."}},
                    status=409,
                )
            return JsonResponse(existing.response_payload, status=existing.status_code)

        record = create_memory_record(payload, actor_id=actor_id, correlation_id=correlation_id)
        response = {"memory": serialize_memory_record(record), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(
            key=idempotency_key,
            request_hash=request_hash,
            response_payload=response,
            status_code=201,
        )
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return JsonResponse({"error": {"code": "INVALID_JSON", "message": "Request body must be valid JSON."}}, status=400)
    except MemoryRecord.DoesNotExist:
        return JsonResponse({"error": {"code": "MEMORY_RECORD_NOT_FOUND", "message": "Superseded memory record was not found."}}, status=404)
    except MemoryError as exc:
        return JsonResponse({"error": {"code": exc.code, "message": str(exc)}}, status=exc.status_code)


def history_search(request):
    record_type = request.GET.get("record_type", "").strip()
    classification = request.GET.get("classification", "").strip()
    verification_status = request.GET.get("verification_status", "").strip()
    source_type = request.GET.get("source_type", "").strip()
    q = request.GET.get("q", "").strip()
    limit_raw = request.GET.get("limit", "20").strip()

    if record_type and record_type not in MemoryRecord.RecordType.values:
        return JsonResponse({"error": {"code": "INVALID_HISTORY_FILTER", "message": "record_type must be valid."}}, status=400)
    if classification and classification not in MemoryRecord.Classification.values:
        return JsonResponse({"error": {"code": "INVALID_HISTORY_FILTER", "message": "classification must be valid."}}, status=400)
    if verification_status and verification_status not in MemoryRecord.VerificationStatus.values:
        return JsonResponse({"error": {"code": "INVALID_HISTORY_FILTER", "message": "verification_status must be valid."}}, status=400)
    if source_type and source_type not in MemoryRecord.SourceType.values:
        return JsonResponse({"error": {"code": "INVALID_HISTORY_FILTER", "message": "source_type must be valid."}}, status=400)
    try:
        limit = int(limit_raw)
    except ValueError:
        return JsonResponse({"error": {"code": "INVALID_HISTORY_FILTER", "message": "limit must be an integer."}}, status=400)
    if limit < 1 or limit > 100:
        return JsonResponse({"error": {"code": "INVALID_HISTORY_FILTER", "message": "limit must be between 1 and 100."}}, status=400)

    records = search_memory_records(
        q=q,
        record_type=record_type,
        classification=classification,
        verification_status=verification_status,
        source_type=source_type,
        limit=limit,
    )
    return JsonResponse({"memory": [serialize_memory_record(record) for record in records]})


# ==============================================================================
# Chief of Staff (CoS) Advanced Operational Endpoints
# ==============================================================================

@require_GET
def cos_critical_path(request):
    objective_id = request.GET.get("objective_id", "").strip() or None
    analysis = CriticalPathEngine.analyze_critical_path(objective_id=objective_id)
    return JsonResponse(analysis)


@csrf_exempt
@require_POST
def cos_dependency_add(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidCosPlanningPayloadError("Request body must be a JSON object.")
        context, existing = idempotent_mutation(request, payload, InvalidCosPlanningPayloadError)
        if existing:
            return existing
        idempotency_key, correlation_id, actor_id, request_hash = context

        task_id = payload.get("task_id", "").strip()
        depends_on_id = payload.get("depends_on_id", "").strip()
        dep_type = payload.get("dependency_type", "BLOCKS").strip()

        if not task_id or not depends_on_id:
            raise InvalidCosPlanningPayloadError("task_id and depends_on_id are required.")

        dep = CriticalPathEngine.add_dependency(task_id=task_id, depends_on_id=depends_on_id, dependency_type=dep_type)
        response = {
            "dependency": {
                "id": str(dep.id),
                "task_id": str(dep.task_id),
                "depends_on_id": str(dep.depends_on_id),
                "dependency_type": dep.dependency_type,
            },
            "correlation_id": correlation_id,
        }
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=201)
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return JsonResponse({"error": {"code": "INVALID_JSON", "message": "Request body must be valid JSON."}}, status=400)
    except CosEngineError as exc:
        return JsonResponse({"error": {"code": exc.code, "message": str(exc)}}, status=exc.status_code)
    except CosPlanningError as exc:
        return JsonResponse({"error": {"code": exc.code, "message": str(exc)}}, status=exc.status_code)


@csrf_exempt
@require_POST
def cos_dependency_remove(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidCosPlanningPayloadError("Request body must be a JSON object.")
        context, existing = idempotent_mutation(request, payload, InvalidCosPlanningPayloadError)
        if existing:
            return existing
        idempotency_key, correlation_id, actor_id, request_hash = context

        task_id = payload.get("task_id", "").strip()
        depends_on_id = payload.get("depends_on_id", "").strip()

        if not task_id or not depends_on_id:
            raise InvalidCosPlanningPayloadError("task_id and depends_on_id are required.")

        removed = CriticalPathEngine.remove_dependency(task_id=task_id, depends_on_id=depends_on_id)
        response = {"removed": removed, "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=200)
        return JsonResponse(response, status=200)
    except json.JSONDecodeError:
        return JsonResponse({"error": {"code": "INVALID_JSON", "message": "Request body must be valid JSON."}}, status=400)
    except CosPlanningError as exc:
        return JsonResponse({"error": {"code": exc.code, "message": str(exc)}}, status=exc.status_code)


@require_GET
def cos_wip_and_stale(request):
    wip = WipAndStaleControlEngine.get_wip_report()
    try:
        stale_days = int(request.GET.get("stale_days", "5"))
    except ValueError:
        stale_days = 5
    stale = WipAndStaleControlEngine.scan_stale_tasks(stale_days=stale_days)
    return JsonResponse({
        "wip_report": wip,
        "stale_tasks": stale,
        "stale_tasks_count": len(stale),
    })


@require_GET
def cos_risks_list(request):
    objective_id = request.GET.get("objective_id", "").strip() or None
    matrix = RiskRegisterEngine.get_risk_matrix(objective_id=objective_id)
    return JsonResponse(matrix)


@csrf_exempt
@require_POST
def cos_risk_create(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidCosPlanningPayloadError("Request body must be a JSON object.")
        context, existing = idempotent_mutation(request, payload, InvalidCosPlanningPayloadError)
        if existing:
            return existing
        idempotency_key, correlation_id, actor_id, request_hash = context

        objective_id = payload.get("objective_id", "").strip()
        title = payload.get("title", "").strip()
        if not objective_id or not title:
            raise InvalidCosPlanningPayloadError("objective_id and title are required.")

        risk = RiskRegisterEngine.create_risk(
            objective_id=objective_id,
            title=title,
            category=payload.get("category", "TECHNICAL"),
            severity=payload.get("severity", "MEDIUM"),
            likelihood=payload.get("likelihood", "MEDIUM"),
            description=payload.get("description", ""),
            mitigation_plan=payload.get("mitigation_plan", ""),
            contingency_plan=payload.get("contingency_plan", ""),
            owner=payload.get("owner", ""),
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        response = {
            "risk": {
                "id": str(risk.id),
                "objective_id": str(risk.objective_id),
                "title": risk.title,
                "category": risk.category,
                "severity": risk.severity,
                "likelihood": risk.likelihood,
                "status": risk.status,
            },
            "correlation_id": correlation_id,
        }
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=201)
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return JsonResponse({"error": {"code": "INVALID_JSON", "message": "Request body must be valid JSON."}}, status=400)
    except CosEngineError as exc:
        return JsonResponse({"error": {"code": exc.code, "message": str(exc)}}, status=exc.status_code)
    except CosPlanningError as exc:
        return JsonResponse({"error": {"code": exc.code, "message": str(exc)}}, status=exc.status_code)


@csrf_exempt
@require_http_methods(["POST", "PUT"])
def cos_risk_update(request, risk_id):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidCosPlanningPayloadError("Request body must be a JSON object.")
        context, existing = idempotent_mutation(request, payload, InvalidCosPlanningPayloadError)
        if existing:
            return existing
        idempotency_key, correlation_id, actor_id, request_hash = context

        risk = RiskRegisterEngine.update_risk(
            risk_id=str(risk_id),
            payload=payload,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        response = {
            "risk": {
                "id": str(risk.id),
                "title": risk.title,
                "status": risk.status,
                "severity": risk.severity,
                "category": risk.category,
            },
            "correlation_id": correlation_id,
        }
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=200)
        return JsonResponse(response, status=200)
    except json.JSONDecodeError:
        return JsonResponse({"error": {"code": "INVALID_JSON", "message": "Request body must be valid JSON."}}, status=400)
    except CosEngineError as exc:
        return JsonResponse({"error": {"code": exc.code, "message": str(exc)}}, status=exc.status_code)
    except CosPlanningError as exc:
        return JsonResponse({"error": {"code": exc.code, "message": str(exc)}}, status=exc.status_code)


@require_GET
def cos_decision_bundle_api(request):
    bundle = CeoDecisionBundleEngine.generate_decision_bundle()
    return JsonResponse(bundle)


@csrf_exempt
@require_POST
def cos_decision_bundle_decide(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidCosPlanningPayloadError("Request body must be a JSON object.")
        context, existing = idempotent_mutation(request, payload, InvalidCosPlanningPayloadError)
        if existing:
            return existing
        idempotency_key, correlation_id, actor_id, request_hash = context

        approval_id = payload.get("approval_id", "").strip()
        decision = payload.get("decision", "").strip().upper()
        reason = payload.get("reason", "").strip()

        if not approval_id or not decision:
            raise InvalidCosPlanningPayloadError("approval_id and decision are required.")

        result = CeoDecisionBundleEngine.execute_decision(
            approval_id=approval_id,
            decision=decision,
            reason=reason,
            decided_by=actor_id,
            correlation_id=correlation_id,
        )
        response = {
            "result": result,
            "correlation_id": correlation_id,
        }
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=200)
        return JsonResponse(response, status=200)
    except json.JSONDecodeError:
        return JsonResponse({"error": {"code": "INVALID_JSON", "message": "Request body must be valid JSON."}}, status=400)
    except CosEngineError as exc:
        return JsonResponse({"error": {"code": exc.code, "message": str(exc)}}, status=exc.status_code)
    except CosPlanningError as exc:
        return JsonResponse({"error": {"code": exc.code, "message": str(exc)}}, status=exc.status_code)


@login_required
@require_GET
def weekly_decision_bundle_page(request):
    bundle = CeoDecisionBundleEngine.generate_decision_bundle()
    return render(request, "core/weekly_decision_bundle.html", {"bundle": bundle})

