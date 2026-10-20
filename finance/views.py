import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from core.models import IdempotencyRecord
from core.services import canonical_hash
from finance.models import FinancialRecord
from finance.services import (
    FinanceError,
    FinanceRecordConflictError,
    InvalidFinancePayloadError,
    create_financial_record,
    finance_summary,
    list_financial_records,
    serialize_financial_record,
    update_reconciliation,
)
from governance.models import RuleEngineWorkItem
from governance.services import InvalidRuleEngineWorkItemUpdateError, update_rule_engine_work_item


def error_response(code: str, message: str, status: int) -> JsonResponse:
    return JsonResponse({"error": {"code": code, "message": message}}, status=status)


def change_headers(request) -> tuple[str, str, str]:
    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    correlation_id = request.headers.get("X-Correlation-ID", "").strip()
    actor_id = request.headers.get("X-Actor-ID", "api").strip() or "api"
    if not idempotency_key or not correlation_id:
        raise InvalidFinancePayloadError("Idempotency-Key and X-Correlation-ID are required.")
    return idempotency_key, correlation_id, actor_id


def dashboard_actor_id(request) -> str:
    if request.user.is_authenticated:
        return str(request.user.get_username())
    return "finance_dashboard"


@login_required
@require_http_methods(["GET", "POST"])
def finance_dashboard(request):
    if request.method == "POST":
        action = request.POST.get("action", "").strip()
        try:
            if action == "complete_rule_engine_work_item":
                item_id = request.POST.get("item_id", "").strip()
                item = RuleEngineWorkItem.objects.get(id=item_id, owner_agent_id="finance_agent")
                update_rule_engine_work_item(
                    str(item.id),
                    status=RuleEngineWorkItem.Status.COMPLETED,
                    actor_id=dashboard_actor_id(request),
                    correlation_id=f"dashboard-finance-rule-work-item-{item.id}",
                )
                messages.success(request, "Finance rule-engine work item completed.")
            else:
                raise ValueError("Unknown finance dashboard action.")
        except (RuleEngineWorkItem.DoesNotExist, InvalidRuleEngineWorkItemUpdateError, ValueError) as exc:
            messages.error(request, str(exc))
        return redirect("finance-dashboard")
    return render(request, "finance/dashboard.html", finance_summary())


@require_GET
def financial_records_list(request):
    record_type = request.GET.get("record_type", "").strip()
    reconciliation_status = request.GET.get("reconciliation_status", "").strip()
    source = request.GET.get("source", "").strip()
    limit_raw = request.GET.get("limit", "100").strip()
    if record_type and record_type not in FinancialRecord.RecordType.values:
        return error_response("INVALID_FINANCE_FILTER", "record_type must be valid.", 400)
    if reconciliation_status and reconciliation_status not in FinancialRecord.ReconciliationStatus.values:
        return error_response("INVALID_FINANCE_FILTER", "reconciliation_status must be valid.", 400)
    try:
        limit = int(limit_raw)
    except ValueError:
        return error_response("INVALID_FINANCE_FILTER", "limit must be an integer.", 400)
    if limit < 1 or limit > 200:
        return error_response("INVALID_FINANCE_FILTER", "limit must be between 1 and 200.", 400)
    records = list_financial_records(
        record_type=record_type,
        reconciliation_status=reconciliation_status,
        source=source,
        limit=limit,
    )
    return JsonResponse({"financial_records": [serialize_financial_record(record) for record in records]})


@csrf_exempt
@require_POST
def financial_record_create(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidFinancePayloadError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        record = create_financial_record(payload, actor_id=actor_id, correlation_id=correlation_id)
        response = {"financial_record": serialize_financial_record(record), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=201)
        return JsonResponse(response, status=201)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except FinanceRecordConflictError as exc:
        return error_response(exc.code, str(exc), 409)
    except InvalidFinancePayloadError as exc:
        return error_response(exc.code, str(exc), 400)
    except FinanceError as exc:
        return error_response(exc.code, str(exc), 400)


@csrf_exempt
@require_POST
def financial_record_reconcile(request, record_id):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidFinancePayloadError("Request body must be a JSON object.")
        idempotency_key, correlation_id, actor_id = change_headers(request)
        request_hash = canonical_hash({"path": request.path, "payload": payload})
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return error_response("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different request.", 409)
            return JsonResponse(existing.response_payload, status=existing.status_code)

        record = update_reconciliation(
            str(record_id),
            status=str(payload.get("reconciliation_status", "")).strip(),
            notes=str(payload.get("notes", "")).strip(),
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        response = {"financial_record": serialize_financial_record(record), "correlation_id": correlation_id}
        IdempotencyRecord.objects.create(key=idempotency_key, request_hash=request_hash, response_payload=response, status_code=200)
        return JsonResponse(response, status=200)
    except json.JSONDecodeError:
        return error_response("INVALID_JSON", "Request body must be valid JSON.", 400)
    except FinancialRecord.DoesNotExist:
        return error_response("FINANCIAL_RECORD_NOT_FOUND", "Financial record was not found.", 404)
    except InvalidFinancePayloadError as exc:
        return error_response(exc.code, str(exc), 400)
