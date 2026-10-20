import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.models import IdempotencyRecord
from core.services import canonical_hash
from operations.models import Task
from portfolio.models import Project, ProjectConnection
from research.services import (
    InvalidResearchContractPayloadError,
    ResearchContractBlockedError,
    ResearchContractError,
    create_research_contract,
    research_adapter_status,
    serialize_research_contract,
)


def error_response(code: str, message: str, status: int) -> JsonResponse:
    return JsonResponse({"error": {"code": code, "message": message}}, status=status)


def change_headers(request):
    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    correlation_id = request.headers.get("X-Correlation-ID", "").strip()
    actor_id = request.headers.get("X-Actor-ID", "api").strip() or "api"
    if not idempotency_key or not correlation_id:
        raise InvalidResearchContractPayloadError("Idempotency-Key and X-Correlation-ID are required.")
    return idempotency_key, correlation_id, actor_id


@csrf_exempt
@require_POST
def research_contract_create(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidResearchContractPayloadError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        contract = create_research_contract(payload, actor_id=actor_id, correlation_id=correlation_id)
        response = {"research_contract": serialize_research_contract(contract), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(
            key=idempotency_key,
            request_hash=request_hash,
            response_payload=response,
            status_code=201,
        )
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except (Task.DoesNotExist, Project.DoesNotExist, ProjectConnection.DoesNotExist):
        return error_response("RESEARCH_CONTRACT_REFERENCE_NOT_FOUND", "Task, project or project connection was not found.", 404)
    except InvalidResearchContractPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ResearchContractBlockedError as exc:
        return error_response(exc.code, str(exc), 409)
    except ResearchContractError as exc:
        return error_response(exc.code, str(exc), 400)


def research_status(request):
    project_id = request.GET.get("project_id", "").strip()
    return JsonResponse({"status": research_adapter_status(project_id=project_id)})
