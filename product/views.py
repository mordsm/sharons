import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from core.models import IdempotencyRecord
from core.services import canonical_hash
from operations.models import Task
from portfolio.models import Project, ProjectConnection
from product.models import ProductSpecContract, ProductSpecDraft
from product.services import (
    InvalidProductContractPayloadError,
    ProductContractBlockedError,
    ProductContractError,
    create_product_spec_contract,
    create_product_spec_draft,
    product_manager_status,
    product_feature_prioritization,
    product_project_roadmap,
    project_product_readiness,
    propose_tasks_from_product_spec_draft,
    review_product_spec_draft,
    serialize_project_product_readiness,
    serialize_product_project_roadmap,
    serialize_product_spec_contract,
    serialize_product_spec_draft,
)
from operations.services import serialize_task


def error_response(code: str, message: str, status: int) -> JsonResponse:
    return JsonResponse({"error": {"code": code, "message": message}}, status=status)


def change_headers(request):
    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    correlation_id = request.headers.get("X-Correlation-ID", "").strip()
    actor_id = request.headers.get("X-Actor-ID", "api").strip() or "api"
    if not idempotency_key or not correlation_id:
        raise InvalidProductContractPayloadError("Idempotency-Key and X-Correlation-ID are required.")
    return idempotency_key, correlation_id, actor_id


@csrf_exempt
@require_POST
def product_spec_contract_create(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidProductContractPayloadError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        contract = create_product_spec_contract(payload, actor_id=actor_id, correlation_id=correlation_id)
        response = {"product_spec_contract": serialize_product_spec_contract(contract), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(
            key=idempotency_key,
            request_hash=request_hash,
            response_payload=response,
            status_code=201,
        )
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except (Task.DoesNotExist, Project.DoesNotExist, ProjectConnection.DoesNotExist, ValueError):
        return error_response("PRODUCT_CONTRACT_REFERENCE_NOT_FOUND", "Task, project or project connection was not found.", 404)
    except InvalidProductContractPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ProductContractBlockedError as exc:
        return error_response(exc.code, str(exc), 409)
    except ProductContractError as exc:
        return error_response(exc.code, str(exc), 400)


@csrf_exempt
@require_POST
def product_spec_draft_create(request, contract_id):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidProductContractPayloadError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        draft = create_product_spec_draft(payload, contract_id=str(contract_id), actor_id=actor_id, correlation_id=correlation_id)
        response = {"product_spec_draft": serialize_product_spec_draft(draft), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(
            key=idempotency_key,
            request_hash=request_hash,
            response_payload=response,
            status_code=201,
        )
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except ProductSpecContract.DoesNotExist:
        return error_response("PRODUCT_CONTRACT_NOT_FOUND", "Product spec contract was not found.", 404)
    except InvalidProductContractPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ProductContractBlockedError as exc:
        return error_response(exc.code, str(exc), 409)
    except ProductContractError as exc:
        return error_response(exc.code, str(exc), 400)


@csrf_exempt
@require_POST
def product_spec_draft_review(request, draft_id):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidProductContractPayloadError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        draft = review_product_spec_draft(payload, draft_id=str(draft_id), actor_id=actor_id, correlation_id=correlation_id)
        response = {"product_spec_draft": serialize_product_spec_draft(draft), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(
            key=idempotency_key,
            request_hash=request_hash,
            response_payload=response,
            status_code=200,
        )
        return JsonResponse(response, status=200)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except ProductSpecDraft.DoesNotExist:
        return error_response("PRODUCT_DRAFT_NOT_FOUND", "Product spec draft was not found.", 404)
    except InvalidProductContractPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ProductContractBlockedError as exc:
        return error_response(exc.code, str(exc), 409)
    except ProductContractError as exc:
        return error_response(exc.code, str(exc), 400)


@csrf_exempt
@require_POST
def product_spec_draft_tasks_propose(request, draft_id):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidProductContractPayloadError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        tasks = propose_tasks_from_product_spec_draft(payload, draft_id=str(draft_id), actor_id=actor_id, correlation_id=correlation_id)
        response = {
            "tasks": [serialize_task(task) for task in tasks],
            "correlation_id": correlation_id,
            "no_external_write": True,
        }
        IdempotencyRecord.objects.create(
            key=idempotency_key,
            request_hash=request_hash,
            response_payload=response,
            status_code=201,
        )
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except ValueError:
        return error_response("INVALID_PRODUCT_CONTRACT_PAYLOAD", "limit must be an integer.", 400)
    except ProductSpecDraft.DoesNotExist:
        return error_response("PRODUCT_DRAFT_NOT_FOUND", "Product spec draft was not found.", 404)
    except InvalidProductContractPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ProductContractBlockedError as exc:
        return error_response(exc.code, str(exc), 409)
    except ProductContractError as exc:
        return error_response(exc.code, str(exc), 400)


@require_GET
def product_project_readiness(request, project_id):
    try:
        return JsonResponse({"readiness": serialize_project_product_readiness(project_product_readiness(project_id=str(project_id)))})
    except Project.DoesNotExist:
        return error_response("PROJECT_NOT_FOUND", "Project was not found.", 404)


@require_GET
def product_project_roadmap_view(request, project_id):
    try:
        return JsonResponse({"roadmap": serialize_product_project_roadmap(product_project_roadmap(project_id=str(project_id)))})
    except Project.DoesNotExist:
        return error_response("PROJECT_NOT_FOUND", "Project was not found.", 404)


@require_GET
def product_status(request):
    project_id = request.GET.get("project_id", "").strip()
    return JsonResponse({"status": product_manager_status(project_id=project_id)})


@require_GET
def product_feature_prioritization_view(request):
    project_id = request.GET.get("project_id", "").strip()
    return JsonResponse({"prioritization": product_feature_prioritization(project_id=project_id)})
