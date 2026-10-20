import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from core.models import IdempotencyRecord
from core.services import canonical_hash
from operations.models import Task
from portfolio.models import Objective
from project_manager.models import BlockerReview, ExecutionReview, MilestoneProposal
from project_manager.services import (
    InvalidProjectManagerPayloadError,
    ProjectManagerBlockedError,
    ProjectManagerError,
    create_blocker_review,
    create_execution_review,
    project_manager_status,
    propose_milestones,
    serialize_blocker_review,
    serialize_execution_review,
    serialize_milestone_proposal,
)


def error_response(code: str, message: str, status: int) -> JsonResponse:
    return JsonResponse({"error": {"code": code, "message": message}}, status=status)


def change_headers(request):
    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    correlation_id = request.headers.get("X-Correlation-ID", "").strip()
    actor_id = request.headers.get("X-Actor-ID", "api").strip() or "api"
    if not idempotency_key or not correlation_id:
        raise InvalidProjectManagerPayloadError("Idempotency-Key and X-Correlation-ID are required.")
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
def project_manager_status_view(request):
    return JsonResponse({"status": project_manager_status()})


@csrf_exempt
@require_POST
def execution_review_create(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidProjectManagerPayloadError("Request body must be a JSON object.")
        context, existing = idempotent_context(request, payload)
        if existing:
            return existing
        idempotency_key, correlation_id, actor_id, request_hash = context
        review = create_execution_review(payload, actor_id=actor_id, correlation_id=correlation_id)
        response = {"execution_review": serialize_execution_review(review), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=201)
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except Objective.DoesNotExist:
        return error_response("OBJECTIVE_NOT_FOUND", "Active objective was not found.", 404)
    except InvalidProjectManagerPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ProjectManagerError as exc:
        return error_response(exc.code, str(exc), 400)


@csrf_exempt
@require_POST
def objective_milestones_propose(request, objective_id):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidProjectManagerPayloadError("Request body must be a JSON object.")
        context, existing = idempotent_context(request, payload)
        if existing:
            return existing
        idempotency_key, correlation_id, actor_id, request_hash = context
        proposals = propose_milestones(payload, objective_id=str(objective_id), actor_id=actor_id, correlation_id=correlation_id)
        response = {"milestone_proposals": [serialize_milestone_proposal(proposal) for proposal in proposals], "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=201)
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except Objective.DoesNotExist:
        return error_response("OBJECTIVE_NOT_FOUND", "Active objective was not found.", 404)
    except InvalidProjectManagerPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ProjectManagerError as exc:
        return error_response(exc.code, str(exc), 400)


@csrf_exempt
@require_POST
def task_blocker_review_create(request, task_id):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidProjectManagerPayloadError("Request body must be a JSON object.")
        context, existing = idempotent_context(request, payload)
        if existing:
            return existing
        idempotency_key, correlation_id, actor_id, request_hash = context
        review = create_blocker_review(payload, task_id=str(task_id), actor_id=actor_id, correlation_id=correlation_id)
        response = {"blocker_review": serialize_blocker_review(review), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=201)
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except Task.DoesNotExist:
        return error_response("TASK_NOT_FOUND", "Task was not found.", 404)
    except InvalidProjectManagerPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ProjectManagerBlockedError as exc:
        return error_response(exc.code, str(exc), 409)
    except ProjectManagerError as exc:
        return error_response(exc.code, str(exc), 400)

