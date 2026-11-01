import json
from datetime import datetime, date

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from core.models import IdempotencyRecord
from core.services import canonical_hash
from operations.models import Task
from portfolio.models import Objective, Project, ProjectConnection
from product.models import (
    ProductSpecContract,
    ProductSpecDraft,
    ProductMilestone,
    ProductFeature,
    ProductFeedback,
    UserResearchContract,
    UserResearchInterview,
    UserResearchQuestion,
)
from product.pm_engine import (
    PrdAndUserStoryEngine,
    RicePrioritizationEngine,
    RoadmapAndMilestoneEngine,
    DiscoveryAndFeedbackEngine,
)
from product.github_issues import (
    create_github_issue_request,
    request_github_issue_approval,
    serialize_github_issue_request,
)
from product.models import GithubIssueRequest
from product.competitive import (
    create_competitive_analysis,
    review_competitive_analysis,
    serialize_competitive_analysis,
)
from product.models import CompetitiveAnalysisDraft
from product.pricing import (
    create_pricing_experiment,
    review_pricing_experiment,
    serialize_pricing_experiment,
)
from product.models import PricingExperimentBrief
from product.user_research import (
    add_user_research_finding,
    add_user_research_interview,
    add_user_research_question,
    create_user_research_contract,
    list_user_research_contracts,
    serialize_user_research_contract,
    serialize_user_research_finding,
    serialize_user_research_interview,
    serialize_user_research_question,
    update_user_research_question,
)
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


def begin_idempotent_post(request):
    payload = json.loads(request.body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise InvalidProductContractPayloadError("Request body must be a JSON object.")
    idempotency_key, correlation_id, actor_id = change_headers(request)
    request_hash = canonical_hash({"path": request.path, "payload": payload})
    existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
    return payload, idempotency_key, correlation_id, actor_id, request_hash, existing


def store_idempotent_response(*, key: str, request_hash: str, response: dict, status_code: int) -> JsonResponse:
    IdempotencyRecord.objects.create(
        key=key,
        request_hash=request_hash,
        response_payload=response,
        status_code=status_code,
    )
    return JsonResponse(response, status=status_code)


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


# ==============================================================================
# Advanced PM Operational APIs (PRD Engine, RICE Ranking, Roadmap, Feedback)
# ==============================================================================

@csrf_exempt
@require_POST
def prd_generate_api(request):
    """
    Decomposes product problem statement into PRD, Acceptance Criteria, and User Stories.
    """
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        project_id = payload.get("project_id")
        title = payload.get("title")
        problem = payload.get("problem_statement")
        if not project_id or not title or not problem:
            return error_response("INVALID_PAYLOAD", "project_id, title, and problem_statement are required.", 400)
        
        target_persona = payload.get("target_persona", "Executive Decision Maker")
        requirements = payload.get("requirements")
        actor_id = request.headers.get("X-Actor-ID", "product_manager").strip() or "product_manager"
        correlation_id = request.headers.get("X-Correlation-ID", "").strip()

        result = PrdAndUserStoryEngine.generate_prd_and_stories(
            project_id=project_id,
            title=title,
            problem_statement=problem,
            target_persona=target_persona,
            requirements=requirements,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        return JsonResponse({"prd": result}, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except Project.DoesNotExist:
        return error_response("PROJECT_NOT_FOUND", "Project was not found.", 404)


@require_GET
def features_rank_api(request):
    """
    Returns the complete product backlog ranked by RICE score with Priority Tiers (P0-P3).
    """
    project_id = request.GET.get("project_id", "").strip() or None
    ranked_backlog = RicePrioritizationEngine.rank_backlog(project_id=project_id)
    return JsonResponse({"features": ranked_backlog, "total_features": len(ranked_backlog)})


@csrf_exempt
@require_POST
def feature_rice_update_api(request, feature_id):
    """
    Updates reach, impact, confidence, or effort for a backlog item and recalculates RICE.
    """
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        reach = payload.get("reach")
        impact = payload.get("impact")
        confidence = payload.get("confidence")
        effort = payload.get("effort")
        actor_id = request.headers.get("X-Actor-ID", "product_manager").strip() or "product_manager"
        correlation_id = request.headers.get("X-Correlation-ID", "").strip()

        result = RicePrioritizationEngine.update_rice(
            feature_id=feature_id,
            reach=reach,
            impact=impact,
            confidence=confidence,
            effort=effort,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        return JsonResponse({"feature": result})
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except ProductFeature.DoesNotExist:
        return error_response("FEATURE_NOT_FOUND", "Product feature was not found.", 404)


@csrf_exempt
@require_POST
def milestone_create_api(request):
    """
    Creates a new Product Roadmap milestone.
    """
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        project_id = payload.get("project_id")
        name = payload.get("name")
        target_date_str = payload.get("target_date")
        if not project_id or not name or not target_date_str:
            return error_response("INVALID_PAYLOAD", "project_id, name, and target_date are required.", 400)

        target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        description = payload.get("description", "")
        release_notes = payload.get("release_notes", "")
        objective_id = payload.get("objective_id") or None

        milestone = RoadmapAndMilestoneEngine.create_milestone(
            project_id=project_id,
            name=name,
            target_date=target_date,
            description=description,
            release_notes=release_notes,
            objective_id=objective_id,
        )
        return JsonResponse({
            "milestone": {
                "id": str(milestone.id),
                "name": milestone.name,
                "target_date": milestone.target_date.isoformat(),
                "status": milestone.status,
                "objective_id": str(milestone.objective_id) if milestone.objective_id else None,
            }
        }, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except Project.DoesNotExist:
        return error_response("PROJECT_NOT_FOUND", "Project was not found.", 404)
    except Objective.DoesNotExist:
        return error_response("OBJECTIVE_NOT_FOUND", "Active objective was not found.", 404)
    except ProductContractBlockedError as exc:
        return error_response(exc.code, str(exc), 409)


@require_GET
def roadmap_timeline_api(request):
    """
    Returns structured roadmap milestones, feature associations, and completion progress.
    """
    project_id = request.GET.get("project_id", "").strip() or None
    roadmap = RoadmapAndMilestoneEngine.get_roadmap(project_id=project_id)
    return JsonResponse({"roadmap": roadmap, "total_milestones": len(roadmap)})


@csrf_exempt
@require_POST
def feedback_ingest_api(request):
    """
    Ingests customer feedback, extracts sentiment, and links to features.
    """
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        project_id = payload.get("project_id")
        source = payload.get("source")
        content = payload.get("content")
        if not project_id or not source or not content:
            return error_response("INVALID_PAYLOAD", "project_id, source, and content are required.", 400)

        user_segment = payload.get("user_segment", "General")
        sentiment = payload.get("sentiment", "NEUTRAL")
        action_item = payload.get("action_item", "")
        feature_id = payload.get("feature_id")

        feedback = DiscoveryAndFeedbackEngine.ingest_feedback(
            project_id=project_id,
            source=source,
            content=content,
            user_segment=user_segment,
            sentiment=sentiment,
            action_item=action_item,
            feature_id=feature_id,
        )
        return JsonResponse({
            "feedback": {
                "id": str(feedback.id),
                "source": feedback.source,
                "sentiment": feedback.sentiment,
                "content": feedback.content,
                "action_item": feedback.action_item,
            }
        }, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except Project.DoesNotExist:
        return error_response("PROJECT_NOT_FOUND", "Project was not found.", 404)


@require_GET
def feedback_summary_api(request):
    """
    Returns sentiment metrics and recent discovery feedback.
    """
    project_id = request.GET.get("project_id", "").strip() or None
    summary = DiscoveryAndFeedbackEngine.get_feedback_summary(project_id=project_id)
    return JsonResponse(summary)


@csrf_exempt
@require_POST
def milestone_objective_link(request, milestone_id):
    try:
        payload, idempotency_key, correlation_id, actor_id, request_hash, existing = begin_idempotent_post(request)
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)
        objective_id = str(payload.get("objective_id", "")).strip()
        if not objective_id:
            raise InvalidProductContractPayloadError("objective_id is required.")
        milestone = RoadmapAndMilestoneEngine.link_objective(
            milestone_id,
            objective_id,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        response = {
            "milestone": {
                "id": str(milestone.id),
                "project_id": str(milestone.project_id),
                "objective_id": str(milestone.objective_id),
                "objective_code": milestone.objective.code,
                "name": milestone.name,
                "no_external_write": True,
            },
            "correlation_id": correlation_id,
        }
        return store_idempotent_response(key=idempotency_key, request_hash=request_hash, response=response, status_code=200)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except ProductMilestone.DoesNotExist:
        return error_response("MILESTONE_NOT_FOUND", "Product milestone was not found.", 404)
    except ProductContractBlockedError as exc:
        return error_response(exc.code, str(exc), 409)
    except InvalidProductContractPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except Objective.DoesNotExist:
        return error_response("OBJECTIVE_NOT_FOUND", "Active objective was not found.", 404)


@csrf_exempt
@require_POST
def user_research_contract_create(request, contract_id):
    try:
        payload, idempotency_key, correlation_id, actor_id, request_hash, existing = begin_idempotent_post(request)
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)
        contract = create_user_research_contract(payload, spec_contract_id=str(contract_id), actor_id=actor_id, correlation_id=correlation_id)
        response = {"user_research_contract": serialize_user_research_contract(contract), "correlation_id": correlation_id}
        return store_idempotent_response(key=idempotency_key, request_hash=request_hash, response=response, status_code=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except ProductSpecContract.DoesNotExist:
        return error_response("PRODUCT_CONTRACT_NOT_FOUND", "Product spec contract was not found.", 404)
    except InvalidProductContractPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ProductContractBlockedError as exc:
        return error_response(exc.code, str(exc), 409)


@require_GET
def user_research_contract_list(request, contract_id):
    if not ProductSpecContract.objects.filter(id=contract_id).exists():
        return error_response("PRODUCT_CONTRACT_NOT_FOUND", "Product spec contract was not found.", 404)
    contracts = list_user_research_contracts(spec_contract_id=str(contract_id))
    return JsonResponse({
        "user_research_contracts": [serialize_user_research_contract(contract) for contract in contracts],
        "no_customer_contact": True,
        "no_external_write": True,
    })


@csrf_exempt
@require_POST
def user_research_interview_create(request, research_id):
    try:
        payload, idempotency_key, correlation_id, actor_id, request_hash, existing = begin_idempotent_post(request)
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)
        interview = add_user_research_interview(payload, contract_id=str(research_id), actor_id=actor_id, correlation_id=correlation_id)
        response = {"interview": serialize_user_research_interview(interview), "correlation_id": correlation_id, "no_customer_contact": True}
        return store_idempotent_response(key=idempotency_key, request_hash=request_hash, response=response, status_code=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except UserResearchContract.DoesNotExist:
        return error_response("USER_RESEARCH_NOT_FOUND", "User research contract was not found.", 404)
    except InvalidProductContractPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ProductContractBlockedError as exc:
        return error_response(exc.code, str(exc), 409)


@csrf_exempt
@require_POST
def user_research_finding_create(request, research_id):
    try:
        payload, idempotency_key, correlation_id, actor_id, request_hash, existing = begin_idempotent_post(request)
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)
        finding = add_user_research_finding(payload, contract_id=str(research_id), actor_id=actor_id, correlation_id=correlation_id)
        response = {"finding": serialize_user_research_finding(finding), "correlation_id": correlation_id, "no_customer_contact": True}
        return store_idempotent_response(key=idempotency_key, request_hash=request_hash, response=response, status_code=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except UserResearchContract.DoesNotExist:
        return error_response("USER_RESEARCH_NOT_FOUND", "User research contract was not found.", 404)
    except UserResearchInterview.DoesNotExist:
        return error_response("USER_RESEARCH_INTERVIEW_NOT_FOUND", "Interview was not found on this research contract.", 404)
    except InvalidProductContractPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ProductContractBlockedError as exc:
        return error_response(exc.code, str(exc), 409)


@csrf_exempt
@require_POST
def user_research_question_create(request, research_id):
    try:
        payload, idempotency_key, correlation_id, actor_id, request_hash, existing = begin_idempotent_post(request)
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)
        question = add_user_research_question(payload, contract_id=str(research_id), actor_id=actor_id, correlation_id=correlation_id)
        response = {"question": serialize_user_research_question(question), "correlation_id": correlation_id, "no_customer_contact": True}
        return store_idempotent_response(key=idempotency_key, request_hash=request_hash, response=response, status_code=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except UserResearchContract.DoesNotExist:
        return error_response("USER_RESEARCH_NOT_FOUND", "User research contract was not found.", 404)
    except InvalidProductContractPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ProductContractBlockedError as exc:
        return error_response(exc.code, str(exc), 409)


@csrf_exempt
@require_POST
def user_research_question_update(request, question_id):
    try:
        payload, idempotency_key, correlation_id, actor_id, request_hash, existing = begin_idempotent_post(request)
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)
        question = update_user_research_question(payload, question_id=str(question_id), actor_id=actor_id, correlation_id=correlation_id)
        response = {"question": serialize_user_research_question(question), "correlation_id": correlation_id, "no_customer_contact": True}
        return store_idempotent_response(key=idempotency_key, request_hash=request_hash, response=response, status_code=200)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except UserResearchQuestion.DoesNotExist:
        return error_response("USER_RESEARCH_QUESTION_NOT_FOUND", "User research question was not found.", 404)
    except InvalidProductContractPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ProductContractBlockedError as exc:
        return error_response(exc.code, str(exc), 409)


@csrf_exempt
@require_POST
def competitive_analysis_create(request, contract_id):
    try:
        payload, idempotency_key, correlation_id, actor_id, request_hash, existing = begin_idempotent_post(request)
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)
        draft = create_competitive_analysis(payload, spec_contract_id=str(contract_id), actor_id=actor_id, correlation_id=correlation_id)
        response = {"competitive_analysis": serialize_competitive_analysis(draft), "correlation_id": correlation_id}
        return store_idempotent_response(key=idempotency_key, request_hash=request_hash, response=response, status_code=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except ProductSpecContract.DoesNotExist:
        return error_response("PRODUCT_CONTRACT_NOT_FOUND", "Product spec contract was not found.", 404)
    except InvalidProductContractPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ProductContractBlockedError as exc:
        return error_response(exc.code, str(exc), 409)


@csrf_exempt
@require_POST
def competitive_analysis_review(request, draft_id):
    try:
        payload, idempotency_key, correlation_id, actor_id, request_hash, existing = begin_idempotent_post(request)
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)
        draft = review_competitive_analysis(payload, draft_id=str(draft_id), actor_id=actor_id, correlation_id=correlation_id)
        response = {"competitive_analysis": serialize_competitive_analysis(draft), "correlation_id": correlation_id}
        return store_idempotent_response(key=idempotency_key, request_hash=request_hash, response=response, status_code=200)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except CompetitiveAnalysisDraft.DoesNotExist:
        return error_response("COMPETITIVE_ANALYSIS_NOT_FOUND", "Competitive analysis was not found.", 404)
    except InvalidProductContractPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ProductContractBlockedError as exc:
        return error_response(exc.code, str(exc), 409)


@csrf_exempt
@require_POST
def pricing_experiment_create(request, contract_id):
    try:
        payload, idempotency_key, correlation_id, actor_id, request_hash, existing = begin_idempotent_post(request)
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)
        brief = create_pricing_experiment(payload, spec_contract_id=str(contract_id), actor_id=actor_id, correlation_id=correlation_id)
        response = {
            "pricing_experiment": serialize_pricing_experiment(brief),
            "correlation_id": correlation_id,
            "no_payment": True,
            "no_spend": True,
        }
        return store_idempotent_response(key=idempotency_key, request_hash=request_hash, response=response, status_code=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except ProductSpecContract.DoesNotExist:
        return error_response("PRODUCT_CONTRACT_NOT_FOUND", "Product spec contract was not found.", 404)
    except InvalidProductContractPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ProductContractBlockedError as exc:
        return error_response(exc.code, str(exc), 409)


@csrf_exempt
@require_POST
def pricing_experiment_review(request, brief_id):
    try:
        payload, idempotency_key, correlation_id, actor_id, request_hash, existing = begin_idempotent_post(request)
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)
        brief = review_pricing_experiment(payload, brief_id=str(brief_id), actor_id=actor_id, correlation_id=correlation_id)
        response = {
            "pricing_experiment": serialize_pricing_experiment(brief),
            "correlation_id": correlation_id,
            "no_payment": True,
            "no_spend": True,
        }
        return store_idempotent_response(key=idempotency_key, request_hash=request_hash, response=response, status_code=200)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except PricingExperimentBrief.DoesNotExist:
        return error_response("PRICING_EXPERIMENT_NOT_FOUND", "Pricing experiment brief was not found.", 404)
    except InvalidProductContractPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ProductContractBlockedError as exc:
        return error_response(exc.code, str(exc), 409)


@csrf_exempt
@require_POST
def github_issue_request_create(request):
    try:
        payload, idempotency_key, correlation_id, actor_id, request_hash, existing = begin_idempotent_post(request)
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)
        issue = create_github_issue_request(payload, actor_id=actor_id, correlation_id=correlation_id)
        response = {"github_issue_request": serialize_github_issue_request(issue), "correlation_id": correlation_id, "external_call": False}
        return store_idempotent_response(key=idempotency_key, request_hash=request_hash, response=response, status_code=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except Project.DoesNotExist:
        return error_response("PROJECT_NOT_FOUND", "Project was not found.", 404)
    except ProjectConnection.DoesNotExist:
        return error_response("PROJECT_CONNECTION_NOT_FOUND", "GitHub connection was not found.", 404)
    except InvalidProductContractPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ProductContractBlockedError as exc:
        return error_response(exc.code, str(exc), 409)


@csrf_exempt
@require_POST
def github_issue_approval_request(request, issue_id):
    try:
        payload, idempotency_key, correlation_id, actor_id, request_hash, existing = begin_idempotent_post(request)
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)
        issue = request_github_issue_approval(payload, issue_id=str(issue_id), actor_id=actor_id, correlation_id=correlation_id)
        response = {"github_issue_request": serialize_github_issue_request(issue), "correlation_id": correlation_id, "external_call": False}
        return store_idempotent_response(key=idempotency_key, request_hash=request_hash, response=response, status_code=200)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except GithubIssueRequest.DoesNotExist:
        return error_response("GITHUB_ISSUE_REQUEST_NOT_FOUND", "GitHub issue request was not found.", 404)
    except InvalidProductContractPayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except ProductContractBlockedError as exc:
        return error_response(exc.code, str(exc), 409)


def product_dashboard_rendered_view(request):
    """
    Interactive Product Manager HTML Dashboard.
    """
    project_id = request.GET.get("project_id", "").strip() or None
    backlog = RicePrioritizationEngine.rank_backlog(project_id=project_id)
    roadmap = RoadmapAndMilestoneEngine.get_roadmap(project_id=project_id)
    feedback_summary = DiscoveryAndFeedbackEngine.get_feedback_summary(project_id=project_id)
    projects = list(Project.objects.all())

    return render(
        request,
        "product/dashboard.html",
        {
            "backlog": backlog,
            "roadmap": roadmap,
            "feedback_summary": feedback_summary,
            "projects": projects,
        },
    )

