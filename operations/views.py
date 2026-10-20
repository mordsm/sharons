import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from core.models import IdempotencyRecord
from core.services import canonical_hash
from operations.forms import TaskAssignForm, TaskEvidenceForm, TaskTransitionForm, TaskVerifyForm
from operations.models import AgentDefinition, Plan, Task
from operations.services import (
    AgentInvokeBlockedError,
    AgentInvokeError,
    EvidenceRecordError,
    InvalidAgentInvokePayloadError,
    InvalidPlanPayloadError,
    InvalidTaskTransitionError,
    InvalidEvidencePayloadError,
    InvalidTaskAssignPayloadError,
    InvalidTaskVerifyPayloadError,
    InvalidTaskUpsertPayloadError,
    PlanCreateError,
    TaskAssignBlockedError,
    TaskAssignError,
    TaskVersionConflictError,
    TaskVerifyBlockedError,
    TaskVerifyError,
    TaskTransitionError,
    TaskUpsertError,
    assign_task,
    agent_performance,
    create_plan,
    invoke_agent,
    list_tasks_for_dashboard,
    record_task_evidence,
    list_available_agents,
    serialize_agent,
    serialize_agent_run,
    serialize_evidence,
    serialize_plan,
    serialize_task,
    task_detail_context,
    transition_task,
    upsert_task,
    verify_task,
)
from portfolio.models import Objective


class TaskTransitionPayloadError(TaskTransitionError):
    code = "INVALID_TASK_TRANSITION_PAYLOAD"


def error_response(code: str, message: str, status: int) -> JsonResponse:
    return JsonResponse({"error": {"code": code, "message": message}}, status=status)


def change_headers(request, error_cls):
    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    correlation_id = request.headers.get("X-Correlation-ID", "").strip()
    actor_id = request.headers.get("X-Actor-ID", "api").strip() or "api"
    if not idempotency_key or not correlation_id:
        raise error_cls("Idempotency-Key and X-Correlation-ID are required.")
    return idempotency_key, correlation_id, actor_id


def dashboard_actor_id(request) -> str:
    if request.user.is_authenticated:
        return str(request.user.get_username())
    return "dashboard"


def dashboard_correlation_id(task_id: str, action: str) -> str:
    return f"dashboard-task-{task_id}-{action}"


def dashboard_idempotency_conflict(*, key: str, payload: dict) -> bool:
    request_hash = canonical_hash(payload)
    existing = IdempotencyRecord.objects.filter(key=key).first()
    return bool(existing and existing.request_hash != request_hash)


def dashboard_idempotency_seen(*, key: str, payload: dict) -> bool:
    request_hash = canonical_hash(payload)
    existing = IdempotencyRecord.objects.filter(key=key).first()
    return bool(existing and existing.request_hash == request_hash)


def record_dashboard_idempotency(*, key: str, payload: dict, response_payload: dict) -> None:
    IdempotencyRecord.objects.create(
        key=key,
        request_hash=canonical_hash(payload),
        response_payload=response_payload,
        status_code=303,
    )


def agents_list(request):
    capability = request.GET.get("capability", "").strip()
    data_class = request.GET.get("data_class", "").strip()
    max_risk_raw = request.GET.get("max_risk_level", "").strip()
    max_risk_level = None
    if max_risk_raw:
        try:
            max_risk_level = int(max_risk_raw)
        except ValueError:
            return error_response("INVALID_AGENT_FILTER", "max_risk_level must be an integer.", 400)

    agents = list_available_agents(
        capability=capability,
        data_class=data_class,
        max_risk_level=max_risk_level,
    )
    return JsonResponse({"agents": [serialize_agent(agent) for agent in agents]})


@require_GET
def agent_performance_detail(request, agent_id):
    try:
        return JsonResponse({"performance": agent_performance(str(agent_id))})
    except AgentDefinition.DoesNotExist:
        return error_response("AGENT_NOT_FOUND", "Agent was not found.", 404)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def plans_collection(request):
    if request.method == "GET":
        objective_id = request.GET.get("objective_id", "").strip()
        status = request.GET.get("status", "").strip()
        plans = Plan.objects.select_related("objective").order_by("-created_at")
        if objective_id:
            plans = plans.filter(objective_id=objective_id)
        if status:
            if status not in Plan.Status.values:
                return error_response("INVALID_PLAN_FILTER", "status must be a valid plan status.", 400)
            plans = plans.filter(status=status)
        return JsonResponse({"plans": [serialize_plan(plan) for plan in plans[:100]]})

    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidPlanPayloadError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = change_headers(request, InvalidPlanPayloadError)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        plan = create_plan(payload, actor_id=actor_id, correlation_id=correlation_id)
        response = {"plan": serialize_plan(plan), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(
            key=idempotency_key,
            request_hash=request_hash,
            response_payload=response,
            status_code=201,
        )
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except Objective.DoesNotExist:
        return error_response("OBJECTIVE_NOT_FOUND", "Active objective was not found.", 404)
    except InvalidPlanPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except PlanCreateError as exc:
        return error_response(exc.code, str(exc), 400)


@require_GET
def plan_detail(request, plan_id):
    try:
        return JsonResponse({"plan": serialize_plan(Plan.objects.get(id=plan_id))})
    except Plan.DoesNotExist:
        return error_response("PLAN_NOT_FOUND", "Plan was not found.", 404)


@login_required
@require_GET
def task_list_page(request):
    status = request.GET.get("status", "").strip()
    objective_id = request.GET.get("objective_id", "").strip()
    owner_agent_id = request.GET.get("owner_agent_id", "").strip()
    if status and status not in Task.Status.values:
        status = ""
    tasks = list_tasks_for_dashboard(status=status, objective_id=objective_id, owner_agent_id=owner_agent_id)
    return render(
        request,
        "operations/task_list.html",
        {
            "tasks": tasks,
            "statuses": Task.Status.values,
            "selected_status": status,
            "objective_id": objective_id,
            "owner_agent_id": owner_agent_id,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def task_detail_page(request, task_id):
    task = get_object_or_404(Task, id=task_id)
    if request.method == "POST":
        action = request.POST.get("action", "").strip()
        actor_id = dashboard_actor_id(request)
        correlation_id = dashboard_correlation_id(str(task.id), action)

        try:
            if action == "transition":
                form = TaskTransitionForm(request.POST)
                if not form.is_valid():
                    raise ValueError("Transition form is invalid.")
                payload = {
                    "action": action,
                    "task_id": str(task.id),
                    "to_status": form.cleaned_data["to_status"],
                    "expected_version": form.cleaned_data["expected_version"],
                }
                idempotency_key = form.cleaned_data["idempotency_key"]
                if dashboard_idempotency_conflict(key=idempotency_key, payload=payload):
                    raise ValueError("Idempotency key was already used for a different dashboard action.")
                if not dashboard_idempotency_seen(key=idempotency_key, payload=payload):
                    updated = transition_task(
                        str(task.id),
                        to_status=payload["to_status"],
                        expected_version=payload["expected_version"],
                        actor_id=actor_id,
                        correlation_id=correlation_id,
                    )
                    record_dashboard_idempotency(
                        key=idempotency_key,
                        payload=payload,
                        response_payload={"task_id": str(updated.id), "status": updated.status, "version": updated.version},
                    )
                messages.success(request, "Task transition recorded.")

            elif action == "assign":
                form = TaskAssignForm(request.POST)
                if not form.is_valid():
                    raise ValueError("Assign form is invalid.")
                payload = {
                    "action": action,
                    "task_id": str(task.id),
                    "agent_id": form.cleaned_data["agent_id"],
                    "expected_version": form.cleaned_data["expected_version"],
                }
                idempotency_key = form.cleaned_data["idempotency_key"]
                if dashboard_idempotency_conflict(key=idempotency_key, payload=payload):
                    raise ValueError("Idempotency key was already used for a different dashboard action.")
                if not dashboard_idempotency_seen(key=idempotency_key, payload=payload):
                    updated = assign_task(payload, task_id=str(task.id), actor_id=actor_id, correlation_id=correlation_id)
                    record_dashboard_idempotency(
                        key=idempotency_key,
                        payload=payload,
                        response_payload={"task_id": str(updated.id), "status": updated.status, "version": updated.version},
                    )
                messages.success(request, "Task assigned.")

            elif action == "evidence":
                form = TaskEvidenceForm(request.POST)
                if not form.is_valid():
                    raise ValueError("Evidence form is invalid.")
                payload = {
                    "action": action,
                    "task_id": str(task.id),
                    "kind": form.cleaned_data["kind"],
                    "uri_or_reference": form.cleaned_data["uri_or_reference"],
                    "checksum": form.cleaned_data["checksum"],
                    "verified": form.cleaned_data["verified"],
                }
                idempotency_key = form.cleaned_data["idempotency_key"]
                if dashboard_idempotency_conflict(key=idempotency_key, payload=payload):
                    raise ValueError("Idempotency key was already used for a different dashboard action.")
                if not dashboard_idempotency_seen(key=idempotency_key, payload=payload):
                    evidence = record_task_evidence(payload, task_id=str(task.id), actor_id=actor_id, correlation_id=correlation_id)
                    record_dashboard_idempotency(
                        key=idempotency_key,
                        payload=payload,
                        response_payload={"evidence_id": str(evidence.id), "task_id": str(task.id)},
                    )
                messages.success(request, "Evidence recorded.")

            elif action == "verify":
                form = TaskVerifyForm(request.POST)
                if not form.is_valid():
                    raise ValueError("Verify form is invalid.")
                payload = {
                    "action": action,
                    "task_id": str(task.id),
                    "mark_passed": form.cleaned_data["mark_passed"],
                    "notes": form.cleaned_data["notes"],
                }
                idempotency_key = form.cleaned_data["idempotency_key"]
                if dashboard_idempotency_conflict(key=idempotency_key, payload=payload):
                    raise ValueError("Idempotency key was already used for a different dashboard action.")
                if not dashboard_idempotency_seen(key=idempotency_key, payload=payload):
                    updated = verify_task(payload, task_id=str(task.id), actor_id=actor_id, correlation_id=correlation_id)
                    record_dashboard_idempotency(
                        key=idempotency_key,
                        payload=payload,
                        response_payload={"task_id": str(updated.id), "status": updated.status, "version": updated.version},
                    )
                messages.success(request, "Task verification recorded.")

            else:
                raise ValueError("Unknown task action.")
        except Exception as exc:
            messages.error(request, str(exc))
        return redirect("task-detail", task_id=task.id)

    context = task_detail_context(str(task.id))
    context.update(
        {
            "transition_form": TaskTransitionForm(initial={"expected_version": task.version}),
            "assign_form": TaskAssignForm(initial={"expected_version": task.version}),
            "evidence_form": TaskEvidenceForm(),
            "verify_form": TaskVerifyForm(),
        }
    )
    return render(request, "operations/task_detail.html", context)


@csrf_exempt
@require_POST
def agent_invoke(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidAgentInvokePayloadError("Request body must be a JSON object.")

        idempotency_key, correlation_id, actor_id = change_headers(request, InvalidAgentInvokePayloadError)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        agent_run = invoke_agent(payload, actor_id=actor_id, correlation_id=correlation_id)
        response = {"agent_run": serialize_agent_run(agent_run), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(
            key=idempotency_key,
            request_hash=request_hash,
            response_payload=response,
            status_code=201,
        )
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except (Task.DoesNotExist, AgentDefinition.DoesNotExist):
        return error_response("AGENT_OR_TASK_NOT_FOUND", "Agent or task was not found.", 404)
    except InvalidAgentInvokePayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except AgentInvokeBlockedError as exc:
        return error_response(exc.code, str(exc), 409)
    except AgentInvokeError as exc:
        return error_response(exc.code, str(exc), 400)


@csrf_exempt
@require_POST
def task_upsert(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidTaskUpsertPayloadError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = change_headers(request, InvalidTaskUpsertPayloadError)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        task, created = upsert_task(payload, actor_id=actor_id, correlation_id=correlation_id)
        response = {"task": serialize_task(task), "created": created, "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(
            key=idempotency_key,
            request_hash=request_hash,
            response_payload=response,
            status_code=201 if created else 200,
        )
        return JsonResponse(response, status=201 if created else 200)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except (Objective.DoesNotExist, Plan.DoesNotExist):
        return error_response("OBJECTIVE_OR_PLAN_NOT_FOUND", "Active objective or matching plan was not found.", 404)
    except InvalidTaskUpsertPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except TaskUpsertError as exc:
        return error_response(exc.code, str(exc), 400)


@csrf_exempt
@require_POST
def task_transition(request, task_id):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise TaskTransitionPayloadError("Request body must be a JSON object.")

        idempotency_key, correlation_id, actor_id = change_headers(request, TaskTransitionPayloadError)

        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        to_status = str(payload.get("to_status", "")).strip()
        if to_status not in Task.Status.values:
            raise TaskTransitionPayloadError("to_status is required and must be a valid task status.")

        try:
            expected_version = int(payload["expected_version"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TaskTransitionPayloadError("expected_version is required and must be an integer.") from exc

        task = transition_task(
            str(task_id),
            to_status=to_status,
            expected_version=expected_version,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        response = {
            "task_id": str(task.id),
            "correlation_id": correlation_id,
            "status": task.status,
            "version": task.version,
        }
        IdempotencyRecord.objects.create(
            key=idempotency_key,
            request_hash=request_hash,
            response_payload=response,
            status_code=200,
        )
        return JsonResponse(response, status=200)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except Task.DoesNotExist:
        return error_response("TASK_NOT_FOUND", "Task was not found.", 404)
    except TaskTransitionPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except InvalidTaskTransitionError as exc:
        return error_response(exc.code, str(exc), 409)
    except TaskTransitionError as exc:
        return error_response(exc.code, str(exc), 409)


@csrf_exempt
@require_POST
def task_assign(request, task_id):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidTaskAssignPayloadError("Request body must be a JSON object.")

        idempotency_key, correlation_id, actor_id = change_headers(request, InvalidTaskAssignPayloadError)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        task = assign_task(
            payload,
            task_id=str(task_id),
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        response = {"task": serialize_task(task), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(
            key=idempotency_key,
            request_hash=request_hash,
            response_payload=response,
            status_code=200,
        )
        return JsonResponse(response, status=200)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except Task.DoesNotExist:
        return error_response("TASK_NOT_FOUND", "Task was not found.", 404)
    except InvalidTaskAssignPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except TaskAssignBlockedError as exc:
        return error_response(exc.code, str(exc), 409)
    except TaskVersionConflictError as exc:
        return error_response(exc.code, str(exc), 409)
    except TaskAssignError as exc:
        return error_response(exc.code, str(exc), 400)


@csrf_exempt
@require_POST
def task_evidence(request, task_id):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidEvidencePayloadError("Request body must be a JSON object.")

        idempotency_key, correlation_id, actor_id = change_headers(request, InvalidEvidencePayloadError)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        evidence = record_task_evidence(
            payload,
            task_id=str(task_id),
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        response = {"evidence": serialize_evidence(evidence), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(
            key=idempotency_key,
            request_hash=request_hash,
            response_payload=response,
            status_code=201,
        )
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except Task.DoesNotExist:
        return error_response("TASK_NOT_FOUND", "Task was not found.", 404)
    except InvalidEvidencePayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except EvidenceRecordError as exc:
        return error_response(exc.code, str(exc), 400)


@csrf_exempt
@require_POST
def task_verify(request, task_id):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidTaskVerifyPayloadError("Request body must be a JSON object.")

        idempotency_key, correlation_id, actor_id = change_headers(request, InvalidTaskVerifyPayloadError)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        task = verify_task(
            payload,
            task_id=str(task_id),
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        response = {"task": serialize_task(task), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(
            key=idempotency_key,
            request_hash=request_hash,
            response_payload=response,
            status_code=200,
        )
        return JsonResponse(response, status=200)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except Task.DoesNotExist:
        return error_response("TASK_NOT_FOUND", "Task was not found.", 404)
    except InvalidTaskVerifyPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except TaskVerifyBlockedError as exc:
        return error_response(exc.code, str(exc), 409)
    except TaskVerifyError as exc:
        return error_response(exc.code, str(exc), 400)
