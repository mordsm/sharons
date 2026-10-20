from django.db import IntegrityError, transaction

from governance.models import AuditEvent, RuleEvaluation
from governance.services import evaluate_rules, evaluate_rules_engine_dry_run, record_inbox_event
from mailbox.models import MockEmailMessage


class MailboxError(Exception):
    code = "MAILBOX_ERROR"


class InvalidEmailPayloadError(MailboxError):
    code = "INVALID_EMAIL_PAYLOAD"


class EmailAlreadyIngestedError(MailboxError):
    code = "EMAIL_ALREADY_INGESTED"


def classify_email(*, subject: str, body: str, sender: str) -> str:
    text = f"{subject} {body} {sender}".lower()
    if any(term in text for term in ["password", "medical", "diagnosis", "passport", "id number", "personal sensitive"]):
        return MockEmailMessage.Classification.PERSONAL_SENSITIVE
    if any(term in text for term in ["invoice", "receipt", "tax invoice", "חשבונית", "קבלה"]):
        return MockEmailMessage.Classification.INVOICE
    if any(term in text for term in ["unsubscribe", "lottery", "winner", "free money", "crypto giveaway"]):
        return MockEmailMessage.Classification.SPAM
    if any(term in text for term in ["approve", "decision", "choose", "sign off"]):
        return MockEmailMessage.Classification.DECISION
    if any(term in text for term in ["todo", "task", "please do", "follow up", "action item"]):
        return MockEmailMessage.Classification.TASK
    return MockEmailMessage.Classification.INFORMATION


def proposed_action_for(classification: str, *, subject: str, sender: str) -> dict:
    if classification == MockEmailMessage.Classification.INVOICE:
        return {"type": "MANUAL_REVIEW", "target": "finance", "title": subject}
    if classification == MockEmailMessage.Classification.TASK:
        return {"type": "PROPOSE_TASK", "title": subject, "source": sender}
    if classification == MockEmailMessage.Classification.DECISION:
        return {"type": "REQUEST_INTERNAL_DECISION", "title": subject, "source": sender}
    if classification == MockEmailMessage.Classification.PERSONAL_SENSITIVE:
        return {"type": "RESTRICT_AND_REVIEW", "title": subject, "source": sender}
    if classification == MockEmailMessage.Classification.SPAM:
        return {"type": "IGNORE", "title": subject}
    return {"type": "STORE_INFORMATION", "title": subject, "source": sender}


def rules_engine_email_payload(
    *,
    source: str,
    external_event_id: str,
    sender: str,
    subject: str,
    body: str,
    classification: str,
    correlation_id: str,
) -> dict:
    from django.utils import timezone

    sensitivity_hint = None
    if classification == MockEmailMessage.Classification.PERSONAL_SENSITIVE:
        sensitivity_hint = "sensitive"
    elif classification == MockEmailMessage.Classification.INVOICE:
        sensitivity_hint = "financial"

    extracted_deadline = None
    lower_text = f"{subject} {body}".lower()
    if any(term in lower_text for term in ["tomorrow", "tuesday", "deadline", "due"]):
        extracted_deadline = "UNKNOWN"

    return {
        "source": source,
        "external_event_id": external_event_id,
        "event": {
            "event_id": f"email-{source}-{external_event_id}",
            "event_type": "inbound_email.route",
            "event_version": "1.0",
            "source": "sharons_mailbox",
            "user_id": "sharon",
            "occurred_at": timezone.now().isoformat(),
            "payload": {
                "source_mailbox": source,
                "message_id": external_event_id,
                "received_at": timezone.now().isoformat(),
                "from_address": sender,
                "to_addresses": [],
                "subject": subject,
                "body_excerpt_redacted": body[:240],
                "attachments": ["invoice_or_receipt"] if classification == MockEmailMessage.Classification.INVOICE else [],
                "sender_relationship": "known",
                "sensitivity_hint": sensitivity_hint,
                "extracted_deadline": extracted_deadline,
                "classification_hint": classification,
                "confidence_hint": 0.85,
            },
            "metadata": {"dry_run": True, "trace_id": correlation_id},
        },
    }


def serialize_email_message(message: MockEmailMessage) -> dict:
    return {
        "id": str(message.id),
        "source": message.source,
        "external_event_id": message.external_event_id,
        "sender": message.sender,
        "subject": message.subject,
        "classification": message.classification,
        "proposed_action": message.proposed_action,
        "rule_decision": message.rule_decision,
        "rule_reason_codes": message.rule_reason_codes,
        "inbox_event_id": str(message.inbox_event_id) if message.inbox_event_id else None,
        "created_at": message.created_at.isoformat(),
    }


def list_email_messages(*, classification: str = "", limit: int = 100):
    messages = MockEmailMessage.objects.all()
    if classification:
        messages = messages.filter(classification=classification)
    return messages[:limit]


def ingest_mock_email(payload: dict, *, actor_id: str, correlation_id: str) -> tuple[MockEmailMessage, bool]:
    source = str(payload.get("source", "gmail_mock")).strip()
    external_event_id = str(payload.get("external_event_id", "")).strip()
    sender = str(payload.get("sender", "")).strip()
    subject = str(payload.get("subject", "")).strip()
    body = str(payload.get("body", "")).strip()
    if not source or not external_event_id or not sender or not subject:
        raise InvalidEmailPayloadError("source, external_event_id, sender and subject are required.")

    actor = actor_id.strip() or "api"
    classification = classify_email(subject=subject, body=body, sender=sender)
    proposed_action = proposed_action_for(classification, subject=subject, sender=sender)
    event_payload = {
        "event_type": "mock_email_received",
        "source": source,
        "external_event_id": external_event_id,
        "sender": sender,
        "subject": subject,
        "classification": classification,
        "proposed_action_type": proposed_action["type"],
    }

    with transaction.atomic():
        inbox_event, _created = record_inbox_event(
            source=source,
            external_event_id=external_event_id,
            payload=event_payload,
            correlation_id=correlation_id,
            actor_id=actor,
        )
        existing = MockEmailMessage.objects.filter(source=source, external_event_id=external_event_id).first()
        if existing:
            return existing, False

        evaluation = evaluate_rules(event_payload, event_id=f"email:{source}:{external_event_id}")
        rules_engine_run, approval = evaluate_rules_engine_dry_run(
            rules_engine_email_payload(
                source=source,
                external_event_id=external_event_id,
                sender=sender,
                subject=subject,
                body=body,
                classification=classification,
                correlation_id=correlation_id,
            ),
            actor_id=actor,
            correlation_id=correlation_id,
        )
        proposed_action = {
            **proposed_action,
            "rules_engine_run_id": str(rules_engine_run.id),
            "rules_engine_decision": rules_engine_run.final_decision,
            "approval_id": str(approval.id) if approval else "",
            "dry_run": True,
        }
        try:
            message = MockEmailMessage.objects.create(
                source=source,
                external_event_id=external_event_id,
                sender=sender,
                subject=subject,
                body=body,
                classification=classification,
                proposed_action=proposed_action,
                rule_decision=evaluation.decision,
                rule_reason_codes=evaluation.reason_codes,
                inbox_event_id=inbox_event.id,
            )
        except IntegrityError as exc:
            raise EmailAlreadyIngestedError("Email was already ingested.") from exc
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="mailbox.mock_email.ingested",
            object_type="mailbox.MockEmailMessage",
            object_id=str(message.id),
            correlation_id=correlation_id,
            metadata={
                "source": source,
                "external_event_id": external_event_id,
                "classification": classification,
                "proposed_action_type": proposed_action["type"],
                "rule_decision": evaluation.decision,
                "requires_approval_before_external_action": True,
            },
        )
    return message, True
