import json

from django.db import IntegrityError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

from core.models import IdempotencyRecord
from core.services import canonical_hash
from portfolio.models import Project
from portfolio.models import Objective, ObjectiveProjectLink, ProjectStateAssessment
from portfolio.services import (
    ProjectRegistryError,
    create_project,
    create_project_connection,
    register_known_90_day_projects,
    serialize_connection,
    serialize_objective_project_link,
    serialize_objective,
    serialize_project,
    serialize_project_state_assessment,
)


def error_response(code: str, message: str, status: int) -> JsonResponse:
    return JsonResponse({"error": {"code": code, "message": message}}, status=status)


def require_change_headers(request) -> tuple[str, str, str]:
    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    correlation_id = request.headers.get("X-Correlation-ID", "").strip()
    actor_id = request.headers.get("X-Actor-ID", "api").strip() or "api"
    if not idempotency_key or not correlation_id:
        raise ProjectRegistryError("Idempotency-Key and X-Correlation-ID are required.")
    return idempotency_key, correlation_id, actor_id


@csrf_exempt
@require_http_methods(["GET", "POST"])
def projects_collection(request):
    if request.method == "GET":
        projects = Project.objects.order_by("slug")
        return JsonResponse({"projects": [serialize_project(project) for project in projects]})

    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ProjectRegistryError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = require_change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        project = create_project(payload, actor_id=actor_id, correlation_id=correlation_id)
        response = {"project": serialize_project(project)}
        IdempotencyRecord.objects.create(
            key=idempotency_key,
            request_hash=request_hash,
            response_payload=response,
            status_code=201,
        )
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except IntegrityError:
        return error_response("PROJECT_CONFLICT", "Project conflicts with an existing record.", 409)
    except ProjectRegistryError as exc:
        return error_response(exc.code, str(exc), 400)


@require_http_methods(["GET"])
def objectives_list(request):
    objectives = Objective.objects.select_related("strategy_version").order_by("code")
    return JsonResponse({"objectives": [serialize_objective(objective) for objective in objectives]})


@csrf_exempt
@require_POST
def known_90_day_projects_register(request):
    try:
        payload = {}
        if request.body:
            payload = json.loads(request.body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ProjectRegistryError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = require_change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        result = register_known_90_day_projects(actor_id=actor_id, correlation_id=correlation_id)
        response = {
            "projects": [serialize_project(project) for project in result["projects"]],
            "links": [serialize_objective_project_link(link) for link in result["links"]],
            "assessments": [serialize_project_state_assessment(assessment) for assessment in result["assessments"]],
        }
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=201)
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except ProjectRegistryError as exc:
        return error_response(exc.code, str(exc), 400)


@require_http_methods(["GET"])
def objective_project_links_list(request):
    links = ObjectiveProjectLink.objects.select_related("objective", "project").order_by("objective__code", "project__slug")
    objective_code = request.GET.get("objective_code", "").strip()
    if objective_code:
        links = links.filter(objective__code=objective_code)
    return JsonResponse({"links": [serialize_objective_project_link(link) for link in links]})


@require_http_methods(["GET"])
def project_state_assessments_list(request):
    assessments = ProjectStateAssessment.objects.select_related("objective", "project").order_by("project__slug", "-created_at")
    project_slug = request.GET.get("project_slug", "").strip()
    objective_code = request.GET.get("objective_code", "").strip()
    status = request.GET.get("status", ProjectStateAssessment.Status.CURRENT).strip()
    if project_slug:
        assessments = assessments.filter(project__slug=project_slug)
    if objective_code:
        assessments = assessments.filter(objective__code=objective_code)
    if status:
        assessments = assessments.filter(status=status)
    return JsonResponse({"assessments": [serialize_project_state_assessment(assessment) for assessment in assessments]})


@csrf_exempt
@require_POST
def project_connections_create(request, project_id):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ProjectRegistryError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = require_change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        project = Project.objects.get(id=project_id)
        connection = create_project_connection(project, payload, actor_id=actor_id, correlation_id=correlation_id)
        response = {"connection": serialize_connection(connection)}
        IdempotencyRecord.objects.create(
            key=idempotency_key,
            request_hash=request_hash,
            response_payload=response,
            status_code=201,
        )
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except Project.DoesNotExist:
        return error_response("PROJECT_NOT_FOUND", "Project was not found.", 404)
    except (IntegrityError, ValueError):
        return error_response("PROJECT_CONNECTION_CONFLICT", "Project connection could not be created.", 409)
    except ProjectRegistryError as exc:
        return error_response(exc.code, str(exc), 400)
