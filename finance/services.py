from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.core.exceptions import ValidationError

from finance.models import FinancialRecord
from governance.models import AuditEvent, RuleEngineWorkItem
from governance.services import evaluate_rules_engine_dry_run


class FinanceError(Exception):
    code = "FINANCE_ERROR"


class InvalidFinancePayloadError(FinanceError):
    code = "INVALID_FINANCE_PAYLOAD"


class FinanceRecordConflictError(FinanceError):
    code = "FINANCE_RECORD_CONFLICT"


def serialize_financial_record(record: FinancialRecord) -> dict:
    return {
        "id": str(record.id),
        "record_type": record.record_type,
        "occurred_on": record.occurred_on.isoformat(),
        "amount": str(record.amount),
        "currency": record.currency,
        "source": record.source,
        "category": record.category,
        "description": record.description,
        "external_reference": record.external_reference,
        "reconciliation_status": record.reconciliation_status,
        "reconciliation_notes": record.reconciliation_notes,
        "metadata": record.metadata,
        "created_by": record.created_by,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


def list_financial_records(*, record_type: str = "", reconciliation_status: str = "", source: str = "", limit: int = 100):
    records = FinancialRecord.objects.all()
    if record_type:
        records = records.filter(record_type=record_type)
    if reconciliation_status:
        records = records.filter(reconciliation_status=reconciliation_status)
    if source:
        records = records.filter(source=source)
    return records[:limit]


def finance_summary() -> dict:
    records = FinancialRecord.objects.all()
    income_total = sum((record.amount for record in records.filter(record_type=FinancialRecord.RecordType.INCOME)), Decimal("0.00"))
    cost_types = [
        FinancialRecord.RecordType.EXPENSE,
        FinancialRecord.RecordType.SUBSCRIPTION_COST,
        FinancialRecord.RecordType.SERVER_COST,
        FinancialRecord.RecordType.API_COST,
        FinancialRecord.RecordType.OTHER_COST,
    ]
    expense_total = sum((record.amount for record in records.filter(record_type__in=cost_types)), Decimal("0.00"))
    return {
        "income_total": income_total,
        "expense_total": expense_total,
        "net_total": income_total - expense_total,
        "unreconciled_count": records.filter(reconciliation_status=FinancialRecord.ReconciliationStatus.UNRECONCILED).count(),
        "discrepancy_count": records.filter(reconciliation_status=FinancialRecord.ReconciliationStatus.DISCREPANCY).count(),
        "needs_review_count": records.filter(reconciliation_status=FinancialRecord.ReconciliationStatus.NEEDS_REVIEW).count(),
        "rule_engine_work_items": list(
            RuleEngineWorkItem.objects.select_related("run")
            .filter(owner_agent_id="finance_agent")
            .exclude(status__in=[RuleEngineWorkItem.Status.COMPLETED, RuleEngineWorkItem.Status.CANCELLED])
            .order_by("-created_at")[:20]
        ),
        "rule_engine_work_item_counts": {
            status: RuleEngineWorkItem.objects.filter(owner_agent_id="finance_agent", status=status).count()
            for status in RuleEngineWorkItem.Status.values
        },
        "records": list(records[:20]),
    }


def parse_record_payload(payload: dict) -> dict:
    record_type = str(payload.get("record_type", "")).strip()
    if record_type not in FinancialRecord.RecordType.values:
        raise InvalidFinancePayloadError("record_type is required and must be valid.")
    try:
        occurred_on = date.fromisoformat(str(payload.get("occurred_on", "")).strip())
    except ValueError as exc:
        raise InvalidFinancePayloadError("occurred_on must be an ISO date.") from exc
    try:
        amount = Decimal(str(payload.get("amount", "")).strip())
    except (InvalidOperation, ValueError) as exc:
        raise InvalidFinancePayloadError("amount must be a decimal number.") from exc
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise InvalidFinancePayloadError("metadata must be an object.")
    return {
        "record_type": record_type,
        "occurred_on": occurred_on,
        "amount": amount,
        "currency": str(payload.get("currency", "ILS")).strip().upper(),
        "source": str(payload.get("source", "")).strip(),
        "category": str(payload.get("category", "")).strip(),
        "description": str(payload.get("description", "")).strip(),
        "external_reference": str(payload.get("external_reference", "")).strip(),
        "metadata": metadata,
    }


def rules_engine_finance_payload(values: dict, *, correlation_id: str) -> dict:
    from django.utils import timezone

    metadata = values.get("metadata", {})
    document_kind_hint = str(metadata.get("document_kind_hint", "")).strip().lower()
    if not document_kind_hint:
        document_kind_hint = "receipt" if values["record_type"] in {FinancialRecord.RecordType.EXPENSE, FinancialRecord.RecordType.SERVER_COST, FinancialRecord.RecordType.API_COST, FinancialRecord.RecordType.SUBSCRIPTION_COST} else "income"

    return {
        "source": values["source"],
        "external_event_id": values["external_reference"] or f"{values['source']}:{values['occurred_on']}:{values['amount']}",
        "event": {
            "event_id": f"finance-{values['source']}-{values['external_reference'] or correlation_id}",
            "event_type": "finance_document.classify",
            "event_version": "1.0",
            "source": "sharons_finance",
            "user_id": "sharon",
            "occurred_at": timezone.now().isoformat(),
            "payload": {
                "source_system": values["source"],
                "received_at": timezone.now().isoformat(),
                "document_ref": values["external_reference"] or values["description"],
                "document_kind_hint": document_kind_hint,
                "vendor_name": values["description"],
                "amount": float(values["amount"]),
                "currency": values["currency"],
                "paid_at": values["occurred_on"].isoformat() if document_kind_hint == "receipt" else None,
                "payment_method": str(metadata.get("payment_method", "")).strip() or None,
                "account_hint": values["category"] or None,
                "project_or_household_context": str(metadata.get("project", "")).strip() or None,
                "confidence_hint": float(metadata.get("confidence_hint", 0.85)),
            },
            "metadata": {"dry_run": True, "trace_id": correlation_id},
        },
    }


def create_financial_record(payload: dict, *, actor_id: str, correlation_id: str) -> FinancialRecord:
    values = parse_record_payload(payload)
    actor = actor_id.strip() or "api"
    with transaction.atomic():
        rules_engine_run, approval = evaluate_rules_engine_dry_run(
            rules_engine_finance_payload(values, correlation_id=correlation_id),
            actor_id=actor,
            correlation_id=correlation_id,
        )
        values["metadata"] = {
            **values["metadata"],
            "rules_engine_run_id": str(rules_engine_run.id),
            "rules_engine_decision": rules_engine_run.final_decision,
            "rules_engine_reason_codes": rules_engine_run.reason_codes,
            "approval_id": str(approval.id) if approval else "",
            "dry_run": True,
        }
        try:
            record = FinancialRecord.objects.create(**values, created_by=actor)
        except (IntegrityError, ValidationError) as exc:
            raise FinanceRecordConflictError("Financial record external_reference already exists for this source.") from exc
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="finance.record.created",
            object_type="finance.FinancialRecord",
            object_id=str(record.id),
            correlation_id=correlation_id,
            metadata={"record_type": record.record_type, "amount": str(record.amount), "currency": record.currency, "source": record.source},
        )
    return record


def update_reconciliation(record_id: str, *, status: str, notes: str, actor_id: str, correlation_id: str) -> FinancialRecord:
    if status not in FinancialRecord.ReconciliationStatus.values:
        raise InvalidFinancePayloadError("reconciliation_status must be valid.")
    actor = actor_id.strip() or "api"
    with transaction.atomic():
        record = FinancialRecord.objects.select_for_update().get(id=record_id)
        before_status = record.reconciliation_status
        record.reconciliation_status = status
        record.reconciliation_notes = notes.strip()
        record.save(update_fields=["reconciliation_status", "reconciliation_notes", "updated_at"])
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="finance.record.reconciled",
            object_type="finance.FinancialRecord",
            object_id=str(record.id),
            correlation_id=correlation_id,
            metadata={"from_status": before_status, "to_status": record.reconciliation_status},
        )
    return record
