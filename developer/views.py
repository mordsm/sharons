import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from core.models import IdempotencyRecord
from core.services import canonical_hash
from developer.models import DeveloperWorkContract, ImplementationPlan
from developer.services import (
    DeveloperBlockedError,
    DeveloperError,
    InvalidDeveloperPayloadError,
    create_developer_work_contract,
    create_implementation_plan,
    deliver_implementation_plan,
    developer_status,
    serialize_developer_work_contract,
    serialize_implementation_plan,
)
from operations.models import Task
from portfolio.models import Project, ProjectConnection


def error_response(code: str, message: str, status: int) -> JsonResponse:
    return JsonResponse({"error": {"code": code, "message": message}}, status=status)


def change_headers(request):
    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    correlation_id = request.headers.get("X-Correlation-ID", "").strip()
    actor_id = request.headers.get("X-Actor-ID", "api").strip() or "api"
    if not idempotency_key or not correlation_id:
        raise InvalidDeveloperPayloadError("Idempotency-Key and X-Correlation-ID are required.")
    return idempotency_key, correlation_id, actor_id


def idempotent_context(request, payload: dict):
    idempotency_key, correlation_id, actor_id = change_headers(request)
    request_hash = canonical_hash({"path": request.path, "payload": payload})
    existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
    if existing:
        if existing.request_hash != request_hash:
            return None, error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
        return None, JsonResponse(existing.response_payload, status=existing.status_code)
    return (idempotency_key, correlation_id, actor_id, request_hash), None


@require_GET
def developer_status_view(request):
    project_id = request.GET.get("project_id", "").strip()
    return JsonResponse({"status": developer_status(project_id=project_id)})


@csrf_exempt
@require_POST
def developer_work_contract_create(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidDeveloperPayloadError("Request body must be a JSON object.")
        context, existing = idempotent_context(request, payload)
        if existing:
            return existing
        idempotency_key, correlation_id, actor_id, request_hash = context
        contract = create_developer_work_contract(payload, actor_id=actor_id, correlation_id=correlation_id)
        response = {"developer_work_contract": serialize_developer_work_contract(contract), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=201)
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except (Task.DoesNotExist, Project.DoesNotExist, ProjectConnection.DoesNotExist, ValueError):
        return error_response("DEVELOPER_REFERENCE_NOT_FOUND", "Task, project or project connection was not found.", 404)
    except InvalidDeveloperPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except DeveloperBlockedError as exc:
        return error_response(exc.code, str(exc), 409)
    except DeveloperError as exc:
        return error_response(exc.code, str(exc), 400)


@csrf_exempt
@require_POST
def implementation_plan_create(request, contract_id):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidDeveloperPayloadError("Request body must be a JSON object.")
        context, existing = idempotent_context(request, payload)
        if existing:
            return existing
        idempotency_key, correlation_id, actor_id, request_hash = context
        plan = create_implementation_plan(payload, contract_id=str(contract_id), actor_id=actor_id, correlation_id=correlation_id)
        response = {"implementation_plan": serialize_implementation_plan(plan), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=201)
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except DeveloperWorkContract.DoesNotExist:
        return error_response("DEVELOPER_WORK_CONTRACT_NOT_FOUND", "Developer work contract was not found.", 404)
    except InvalidDeveloperPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except DeveloperBlockedError as exc:
        return error_response(exc.code, str(exc), 409)
    except DeveloperError as exc:
        return error_response(exc.code, str(exc), 400)


@csrf_exempt
@require_POST
def implementation_plan_deliver(request, plan_id):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidDeveloperPayloadError("Request body must be a JSON object.")
        context, existing = idempotent_context(request, payload)
        if existing:
            return existing
        idempotency_key, correlation_id, actor_id, request_hash = context
        plan = deliver_implementation_plan(payload, plan_id=str(plan_id), actor_id=actor_id, correlation_id=correlation_id)
        response = {"implementation_plan": serialize_implementation_plan(plan), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=200)
        return JsonResponse(response, status=200)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except ImplementationPlan.DoesNotExist:
        return error_response("IMPLEMENTATION_PLAN_NOT_FOUND", "Implementation plan was not found.", 404)
    except InvalidDeveloperPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except DeveloperBlockedError as exc:
        return error_response(exc.code, str(exc), 409)
    except DeveloperError as exc:
        return error_response(exc.code, str(exc), 400)

