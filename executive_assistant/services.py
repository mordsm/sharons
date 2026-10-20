from django.db import transaction
from django.utils.dateparse import parse_datetime
from django.utils import timezone

from core.services import serialize_weekly_review, weekly_review
from governance.models import ApprovalRequest, AuditEvent, RuleEngineWorkItem
from governance.services import create_approval_request
from mailbox.models import MockEmailMessage
from mailbox.services import ingest_mock_email
from operations.models import AcceptanceCriterion, AgentDefinition, Task
from operations.services import transition_task, upsert_task
from executive_assistant.connectors import get_read_only_connector, list_read_only_connectors
from executive_assistant.models import (
    ExecutiveBrief,
    ExecutiveBriefTaskProposal,
    ExecutiveCalendarEvent,
    ExecutiveEmailDraft,
    ExecutiveProviderSyncConfig,
)


class ExecutiveAssistantError(Exception):
    code = "EXECUTIVE_ASSISTANT_ERROR"


class InvalidExecutiveBriefPayloadError(ExecutiveAssistantError):
    code = "INVALID_EXECUTIVE_BRIEF_PAYLOAD"


class ExecutiveBriefBlockedError(ExecutiveAssistantError):
    code = "EXECUTIVE_BRIEF_BLOCKED"


class ExecutiveProviderConnectorBlockedError(ExecutiveAssistantError):
    code = "EXECUTIVE_PROVIDER_CONNECTOR_BLOCKED"


def ingest_read_only_email(payload: dict, *, actor_id: str, correlation_id: str) -> tuple[MockEmailMessage, bool]:
    source = str(payload.get("source", "email_readonly")).strip() or "email_readonly"
    if source.endswith("_send") or "smtp" in source.lower():
        raise InvalidExecutiveBriefPayloadError("Read-only email ingestion cannot use send-capable sources.")
    read_only_payload = {
        "source": source,
        "external_event_id": str(payload.get("external_event_id", "")).strip(),
        "sender": str(payload.get("sender", "")).strip(),
        "subject": str(payload.get("subject", "")).strip(),
        "body": str(payload.get("body", "")).strip(),
    }
    return ingest_mock_email(read_only_payload, actor_id=actor_id, correlation_id=correlation_id)


def serialize_executive_brief(brief: ExecutiveBrief) -> dict:
    return {
        "id": str(brief.id),
        "brief_type": brief.brief_type,
        "title": brief.title,
        "source_window": brief.source_window,
        "summary": brief.summary,
        "agenda_items": brief.agenda_items,
        "follow_ups": brief.follow_ups,
        "decisions_needed": brief.decisions_needed,
        "inbox_items": brief.inbox_items,
        "status": brief.status,
        "no_external_send": brief.no_external_send,
        "created_by": brief.created_by,
        "created_at": brief.created_at.isoformat(),
    }


def serialize_task_proposal(proposal: ExecutiveBriefTaskProposal) -> dict:
    return {
        "id": str(proposal.id),
        "brief_id": str(proposal.brief_id),
        "task_id": str(proposal.task_id),
        "follow_up_index": proposal.follow_up_index,
        "external_key": proposal.external_key,
        "title": proposal.title,
        "status": proposal.status,
        "review_status": proposal.review_status,
        "reviewed_by": proposal.reviewed_by,
        "reviewed_at": proposal.reviewed_at.isoformat() if proposal.reviewed_at else None,
        "review_note": proposal.review_note,
        "no_external_send": proposal.no_external_send,
        "created_by": proposal.created_by,
        "created_at": proposal.created_at.isoformat(),
    }


def serialize_email_draft(draft: ExecutiveEmailDraft) -> dict:
    return {
        "id": str(draft.id),
        "source_message_id": str(draft.source_message_id) if draft.source_message_id else None,
        "draft_type": draft.draft_type,
        "to_recipients": draft.to_recipients,
        "cc_recipients": draft.cc_recipients,
        "subject": draft.subject,
        "body": draft.body,
        "rationale": draft.rationale,
        "review_status": draft.review_status,
        "reviewed_by": draft.reviewed_by,
        "reviewed_at": draft.reviewed_at.isoformat() if draft.reviewed_at else None,
        "review_note": draft.review_note,
        "no_external_send": draft.no_external_send,
        "created_by": draft.created_by,
        "created_at": draft.created_at.isoformat(),
    }


def serialize_calendar_event(event: ExecutiveCalendarEvent) -> dict:
    return {
        "id": str(event.id),
        "source": event.source,
        "external_event_id": event.external_event_id,
        "title": event.title,
        "starts_at": event.starts_at.isoformat(),
        "ends_at": event.ends_at.isoformat(),
        "organizer": event.organizer,
        "attendees": event.attendees,
        "location": event.location,
        "description": event.description,
        "status": event.status,
        "no_external_schedule": event.no_external_schedule,
        "created_by": event.created_by,
        "created_at": event.created_at.isoformat(),
    }


def serialize_provider_sync_config(config: ExecutiveProviderSyncConfig) -> dict:
    return {
        "id": str(config.id),
        "provider_type": config.provider_type,
        "provider_name": config.provider_name,
        "source": config.source,
        "sync_mode": config.sync_mode,
        "status": config.status,
        "scopes": config.scopes,
        "config": config.config,
        "last_sync_at": config.last_sync_at.isoformat() if config.last_sync_at else None,
        "no_external_action": config.no_external_action,
        "created_by": config.created_by,
        "created_at": config.created_at.isoformat(),
    }


def list_email_drafts(*, review_status: str = "", limit: int = 100):
    drafts = ExecutiveEmailDraft.objects.all()
    if review_status:
        drafts = drafts.filter(review_status=review_status)
    return drafts[:limit]


def list_calendar_events(*, status: str = "", limit: int = 100):
    events = ExecutiveCalendarEvent.objects.all()
    if status:
        events = events.filter(status=status)
    return events[:limit]


def list_provider_sync_configs(*, provider_type: str = "", status: str = "", limit: int = 100):
    configs = ExecutiveProviderSyncConfig.objects.all()
    if provider_type:
        configs = configs.filter(provider_type=provider_type)
    if status:
        configs = configs.filter(status=status)
    return configs[:limit]


def create_provider_sync_config(payload: dict, *, actor_id: str, correlation_id: str) -> tuple[ExecutiveProviderSyncConfig, bool]:
    provider_type = str(payload.get("provider_type", "")).strip()
    provider_name = str(payload.get("provider_name", "")).strip()
    source = str(payload.get("source", "")).strip()
    sync_mode = str(payload.get("sync_mode", ExecutiveProviderSyncConfig.SyncMode.READ_ONLY)).strip()
    status = str(payload.get("status", ExecutiveProviderSyncConfig.Status.PLANNED)).strip()
    scopes = payload.get("scopes", [])
    config_payload = payload.get("config", {})
    if provider_type not in ExecutiveProviderSyncConfig.ProviderType.values:
        raise InvalidExecutiveBriefPayloadError("provider_type must be EMAIL or CALENDAR.")
    if status not in ExecutiveProviderSyncConfig.Status.values:
        raise InvalidExecutiveBriefPayloadError("status must be PLANNED, READY_FOR_CONNECTOR, PAUSED or ERROR.")
    if sync_mode != ExecutiveProviderSyncConfig.SyncMode.READ_ONLY:
        raise InvalidExecutiveBriefPayloadError("Only READ_ONLY sync mode is supported.")
    if not provider_name or not source:
        raise InvalidExecutiveBriefPayloadError("provider_name and source are required.")
    source_lower = source.lower()
    if source_lower.endswith("_send") or source_lower.endswith("_write") or "smtp" in source_lower or "schedule" in source_lower:
        raise InvalidExecutiveBriefPayloadError("source must identify a read-only provider feed.")
    if not isinstance(scopes, list):
        raise InvalidExecutiveBriefPayloadError("scopes must be a list.")
    if not isinstance(config_payload, dict):
        raise InvalidExecutiveBriefPayloadError("config must be an object.")
    blocked_config_keys = {"access_token", "refresh_token", "client_secret", "password", "oauth_token"}
    if blocked_config_keys.intersection({str(key).lower() for key in config_payload}):
        raise InvalidExecutiveBriefPayloadError("config cannot store credentials or OAuth tokens.")

    actor = actor_id.strip() or "api"
    with transaction.atomic():
        sync_config, created = ExecutiveProviderSyncConfig.objects.get_or_create(
            provider_type=provider_type,
            provider_name=provider_name,
            source=source,
            defaults={
                "sync_mode": sync_mode,
                "status": status,
                "scopes": [str(item).strip() for item in scopes if str(item).strip()],
                "config": config_payload,
                "no_external_action": True,
                "created_by": actor,
            },
        )
        if not created:
            sync_config.sync_mode = sync_mode
            sync_config.status = status
            sync_config.scopes = [str(item).strip() for item in scopes if str(item).strip()]
            sync_config.config = config_payload
            sync_config.no_external_action = True
            sync_config.save(update_fields=["sync_mode", "status", "scopes", "config", "no_external_action"])
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="executive_assistant.provider_sync_config.upserted",
            object_type="executive_assistant.ExecutiveProviderSyncConfig",
            object_id=str(sync_config.id),
            correlation_id=correlation_id,
            metadata={
                "provider_type": sync_config.provider_type,
                "provider_name": sync_config.provider_name,
                "source": sync_config.source,
                "sync_mode": sync_config.sync_mode,
                "status": sync_config.status,
                "no_external_action": True,
                "created": created,
            },
        )
    return sync_config, created


def provider_sync_config_readiness(config: ExecutiveProviderSyncConfig) -> dict:
    blockers = []
    warnings = []
    connector = get_read_only_connector(config)
    connector_preflight = connector.preflight(config)
    if config.sync_mode != ExecutiveProviderSyncConfig.SyncMode.READ_ONLY:
        blockers.append("Only READ_ONLY sync mode is supported.")
    if not config.no_external_action:
        blockers.append("External actions must remain disabled.")
    if config.status != ExecutiveProviderSyncConfig.Status.READY_FOR_CONNECTOR:
        blockers.append("Config status must be READY_FOR_CONNECTOR before adapter dry-run.")
    if not config.source:
        blockers.append("Read-only source is required.")
    if not config.scopes:
        warnings.append("No read-only scopes or scope labels have been recorded.")

    source = config.source.lower()
    if source.endswith("_send") or source.endswith("_write") or "smtp" in source or "schedule" in source:
        blockers.append("Source appears to allow external send, write or scheduling.")

    provider_name = config.provider_name.lower()
    expected_markers = {
        ExecutiveProviderSyncConfig.ProviderType.EMAIL: ["gmail", "outlook", "email", "mail"],
        ExecutiveProviderSyncConfig.ProviderType.CALENDAR: ["calendar", "cal", "outlook"],
    }
    if not any(marker in provider_name or marker in source for marker in expected_markers[config.provider_type]):
        warnings.append("Provider name/source do not clearly identify the configured provider type.")
    warnings.extend(connector_preflight.warnings)
    blockers.extend(connector_preflight.blockers)

    return {
        "provider_sync_config": serialize_provider_sync_config(config),
        "ready": not blockers,
        "connector": connector_preflight.as_dict(),
        "external_action_enabled": False,
        "adapter_available": connector_preflight.adapter_available,
        "oauth_configured": connector_preflight.oauth_configured,
        "dry_run_only": True,
        "blockers": blockers,
        "warnings": warnings,
        "next_step": "Implement a provider-specific read-only adapter and OAuth secret handling outside this config.",
    }


def dry_run_provider_sync_config(*, config_id: str, actor_id: str, correlation_id: str) -> dict:
    actor = actor_id.strip() or "api"
    config = ExecutiveProviderSyncConfig.objects.get(id=config_id)
    readiness = provider_sync_config_readiness(config)
    if not readiness["ready"]:
        raise ExecutiveProviderConnectorBlockedError("Provider sync config is not ready for adapter dry-run.")
    connector = get_read_only_connector(config)
    dry_run = connector.dry_run(config)

    AuditEvent.objects.create(
        actor_type=AuditEvent.ActorType.SYSTEM,
        actor_id=actor,
        action="executive_assistant.provider_sync_config.dry_run",
        object_type="executive_assistant.ExecutiveProviderSyncConfig",
        object_id=str(config.id),
        correlation_id=correlation_id,
        metadata={
            "provider_type": config.provider_type,
            "provider_name": config.provider_name,
            "source": config.source,
            "connector_key": readiness["connector"]["connector_key"],
            "adapter_available": readiness["adapter_available"],
            "oauth_configured": readiness["oauth_configured"],
            "external_action_enabled": readiness["external_action_enabled"],
            "records_ingested": dry_run["records_ingested"],
        },
    )
    readiness["dry_run"] = dry_run
    return readiness


def provider_sync_config_plan(*, config_id: str) -> dict:
    config = ExecutiveProviderSyncConfig.objects.get(id=config_id)
    readiness = provider_sync_config_readiness(config)
    connector = get_read_only_connector(config)
    return {
        "readiness": readiness,
        "sync_plan": connector.sync_plan(config),
    }


def provider_readiness_summary() -> dict:
    configs = list(ExecutiveProviderSyncConfig.objects.all())
    items = []
    ready_count = 0
    blocked_count = 0
    warning_count = 0
    for config in configs:
        readiness = provider_sync_config_readiness(config)
        is_ready = bool(readiness["ready"])
        has_warnings = bool(readiness["warnings"])
        ready_count += int(is_ready)
        blocked_count += int(not is_ready)
        warning_count += int(has_warnings)
        items.append(
            {
                "provider_sync_config": readiness["provider_sync_config"],
                "connector_key": readiness["connector"]["connector_key"],
                "ready": is_ready,
                "status": config.status,
                "blocker_count": len(readiness["blockers"]),
                "warning_count": len(readiness["warnings"]),
                "blockers": readiness["blockers"],
                "warnings": readiness["warnings"],
                "external_action_enabled": False,
                "adapter_available": readiness["adapter_available"],
                "oauth_configured": readiness["oauth_configured"],
            }
        )

    return {
        "total": len(configs),
        "ready": ready_count,
        "blocked": blocked_count,
        "with_warnings": warning_count,
        "external_action_enabled": False,
        "real_provider_connections_enabled": False,
        "items": items,
    }


def provider_connector_status() -> dict:
    return {
        "connectors": list_read_only_connectors(),
        "external_email_enabled": False,
        "external_calendar_enabled": False,
        "real_provider_connections_enabled": False,
    }


def executive_assistant_operational_snapshot() -> dict:
    return {
        "status": executive_assistant_status(),
        "provider_connectors": provider_connector_status(),
        "provider_readiness_summary": provider_readiness_summary(),
        "safety": {
            "external_email_enabled": False,
            "external_calendar_enabled": False,
            "external_actions_enabled": False,
            "real_provider_connections_enabled": False,
            "email_send_allowed": False,
            "calendar_schedule_allowed": False,
        },
    }


def _parse_calendar_datetime(value: str, field_name: str):
    parsed = parse_datetime(str(value).strip())
    if parsed is None:
        raise InvalidExecutiveBriefPayloadError(f"{field_name} must be an ISO datetime.")
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone=timezone.get_current_timezone())
    return parsed


def ingest_read_only_calendar_event(payload: dict, *, actor_id: str, correlation_id: str) -> tuple[ExecutiveCalendarEvent, bool]:
    source = str(payload.get("source", "calendar_readonly")).strip() or "calendar_readonly"
    if source.endswith("_write") or "schedule" in source.lower():
        raise InvalidExecutiveBriefPayloadError("Read-only calendar ingestion cannot use schedule-capable sources.")
    external_event_id = str(payload.get("external_event_id", "")).strip()
    title = str(payload.get("title", "")).strip()
    starts_at = _parse_calendar_datetime(str(payload.get("starts_at", "")), "starts_at")
    ends_at = _parse_calendar_datetime(str(payload.get("ends_at", "")), "ends_at")
    attendees = payload.get("attendees", [])
    if not isinstance(attendees, list):
        raise InvalidExecutiveBriefPayloadError("attendees must be a list.")
    status = str(payload.get("status", ExecutiveCalendarEvent.Status.CONFIRMED)).strip() or ExecutiveCalendarEvent.Status.CONFIRMED
    if status not in ExecutiveCalendarEvent.Status.values:
        raise InvalidExecutiveBriefPayloadError("status must be CONFIRMED, TENTATIVE or CANCELLED.")
    if not source or not external_event_id or not title:
        raise InvalidExecutiveBriefPayloadError("source, external_event_id and title are required.")

    actor = actor_id.strip() or "api"
    with transaction.atomic():
        existing = ExecutiveCalendarEvent.objects.filter(source=source, external_event_id=external_event_id).first()
        if existing:
            return existing, False
        event = ExecutiveCalendarEvent.objects.create(
            source=source,
            external_event_id=external_event_id,
            title=title,
            starts_at=starts_at,
            ends_at=ends_at,
            organizer=str(payload.get("organizer", "")).strip(),
            attendees=[str(item).strip() for item in attendees if str(item).strip()],
            location=str(payload.get("location", "")).strip(),
            description=str(payload.get("description", "")).strip(),
            status=status,
            no_external_schedule=True,
            created_by=actor,
        )
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="executive_assistant.calendar_event.ingested",
            object_type="executive_assistant.ExecutiveCalendarEvent",
            object_id=str(event.id),
            correlation_id=correlation_id,
            metadata={
                "source": event.source,
                "external_event_id": event.external_event_id,
                "status": event.status,
                "no_external_schedule": True,
            },
        )
    return event, True


def executive_assistant_queue_counts() -> dict:
    brief_counts = {
        status: ExecutiveBrief.objects.filter(status=status).count()
        for status in ExecutiveBrief.Status.values
    }
    proposal_counts = {
        status: ExecutiveBriefTaskProposal.objects.filter(review_status=status).count()
        for status in ExecutiveBriefTaskProposal.ReviewStatus.values
    }
    ready_briefs_with_follow_ups = ExecutiveBrief.objects.filter(
        status=ExecutiveBrief.Status.READY,
    ).exclude(follow_ups=[]).count()
    return {
        "briefs": brief_counts,
        "task_proposals": proposal_counts,
        "email_drafts": {
            status: ExecutiveEmailDraft.objects.filter(review_status=status).count()
            for status in ExecutiveEmailDraft.ReviewStatus.values
        },
        "calendar_events": {
            status: ExecutiveCalendarEvent.objects.filter(status=status).count()
            for status in ExecutiveCalendarEvent.Status.values
        },
        "provider_sync_configs": {
            status: ExecutiveProviderSyncConfig.objects.filter(status=status).count()
            for status in ExecutiveProviderSyncConfig.Status.values
        },
        "rule_engine_work_items": {
            status: RuleEngineWorkItem.objects.filter(owner_agent_id="executive_assistant", status=status).count()
            for status in RuleEngineWorkItem.Status.values
        },
        "ready_briefs_with_follow_ups": ready_briefs_with_follow_ups,
    }


def executive_assistant_status() -> dict:
    queue_counts = executive_assistant_queue_counts()
    return {
        "agent_id": "executive_assistant",
        "agent_registered": AgentDefinition.objects.filter(agent_id="executive_assistant", active=True).exists(),
        "external_email_enabled": False,
        "external_calendar_enabled": False,
        "briefs": ExecutiveBrief.objects.count(),
        "task_proposals": ExecutiveBriefTaskProposal.objects.count(),
        "email_drafts": ExecutiveEmailDraft.objects.count(),
        "calendar_events": ExecutiveCalendarEvent.objects.count(),
        "provider_sync_configs": ExecutiveProviderSyncConfig.objects.count(),
        "queue_counts": queue_counts,
        "pending_approvals": ApprovalRequest.objects.filter(status=ApprovalRequest.Status.PENDING).count(),
        "mock_inbox_items": MockEmailMessage.objects.count(),
        "assigned_rule_engine_work_items": RuleEngineWorkItem.objects.filter(owner_agent_id="executive_assistant").exclude(
            status__in=[RuleEngineWorkItem.Status.COMPLETED, RuleEngineWorkItem.Status.CANCELLED]
        ).count(),
    }


def _default_reply_body(message: MockEmailMessage) -> str:
    if message.classification == MockEmailMessage.Classification.DECISION:
        return "Thanks. I received this and will review the decision needed before responding with a commitment."
    if message.classification == MockEmailMessage.Classification.TASK:
        return "Thanks. I received this and will track the requested follow-up internally."
    if message.classification == MockEmailMessage.Classification.INVOICE:
        return "Thanks. I received the invoice and will route it for internal finance review."
    return "Thanks. I received this and will review it internally."


def create_email_draft_from_message(payload: dict, *, actor_id: str, correlation_id: str) -> ExecutiveEmailDraft:
    source_message_id = str(payload.get("source_message_id", "")).strip()
    if not source_message_id:
        raise InvalidExecutiveBriefPayloadError("source_message_id is required.")
    draft_type = str(payload.get("draft_type", ExecutiveEmailDraft.DraftType.REPLY)).strip()
    if draft_type not in ExecutiveEmailDraft.DraftType.values:
        raise InvalidExecutiveBriefPayloadError("draft_type must be REPLY, FORWARD or NEW_MESSAGE.")

    actor = actor_id.strip() or "api"
    message = MockEmailMessage.objects.get(id=source_message_id)
    to_recipients = payload.get("to_recipients", [message.sender])
    cc_recipients = payload.get("cc_recipients", [])
    subject = str(payload.get("subject", f"Re: {message.subject}")).strip()
    body = str(payload.get("body", _default_reply_body(message))).strip()
    rationale = str(payload.get("rationale", f"Draft proposed from {message.classification} email classification.")).strip()
    if not isinstance(to_recipients, list) or not all(str(item).strip() for item in to_recipients):
        raise InvalidExecutiveBriefPayloadError("to_recipients must be a non-empty list of recipients.")
    if not isinstance(cc_recipients, list):
        raise InvalidExecutiveBriefPayloadError("cc_recipients must be a list.")
    if not subject or not body:
        raise InvalidExecutiveBriefPayloadError("subject and body are required.")

    with transaction.atomic():
        draft = ExecutiveEmailDraft.objects.create(
            source_message_id=message.id,
            draft_type=draft_type,
            to_recipients=[str(item).strip() for item in to_recipients],
            cc_recipients=[str(item).strip() for item in cc_recipients if str(item).strip()],
            subject=subject,
            body=body,
            rationale=rationale,
            review_status=ExecutiveEmailDraft.ReviewStatus.NEEDS_REVIEW,
            no_external_send=True,
            created_by=actor,
        )
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="executive_assistant.email_draft.created",
            object_type="executive_assistant.ExecutiveEmailDraft",
            object_id=str(draft.id),
            correlation_id=correlation_id,
            metadata={
                "source_message_id": str(message.id),
                "draft_type": draft.draft_type,
                "review_status": draft.review_status,
                "no_external_send": True,
                "requires_approval_before_external_action": True,
            },
        )
    return draft


def review_email_draft(payload: dict, *, draft_id: str, actor_id: str, correlation_id: str) -> ExecutiveEmailDraft:
    decision = str(payload.get("decision", "")).strip()
    if decision not in {ExecutiveEmailDraft.ReviewStatus.APPROVED, ExecutiveEmailDraft.ReviewStatus.REJECTED}:
        raise InvalidExecutiveBriefPayloadError("decision must be APPROVED or REJECTED.")
    review_note = str(payload.get("review_note", "")).strip()
    actor = actor_id.strip() or "api"

    with transaction.atomic():
        draft = ExecutiveEmailDraft.objects.select_for_update().get(id=draft_id)
        if draft.review_status != ExecutiveEmailDraft.ReviewStatus.NEEDS_REVIEW:
            raise ExecutiveBriefBlockedError("Only email drafts needing review can be reviewed.")
        draft.review_status = decision
        draft.reviewed_by = actor
        draft.reviewed_at = timezone.now()
        draft.review_note = review_note
        draft.save(update_fields=["review_status", "reviewed_by", "reviewed_at", "review_note"])
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="executive_assistant.email_draft.reviewed",
            object_type="executive_assistant.ExecutiveEmailDraft",
            object_id=str(draft.id),
            correlation_id=correlation_id,
            metadata={
                "decision": decision,
                "review_note_present": bool(review_note),
                "no_external_send": True,
                "external_send_enabled": False,
            },
        )
    return draft


def create_email_draft_approval_request(payload: dict, *, draft_id: str, actor_id: str, correlation_id: str) -> ApprovalRequest:
    actor = actor_id.strip() or "api"
    expires_in_hours = int(payload.get("expires_in_hours", 24))
    if expires_in_hours < 1 or expires_in_hours > 168:
        raise InvalidExecutiveBriefPayloadError("expires_in_hours must be between 1 and 168.")

    draft = ExecutiveEmailDraft.objects.get(id=draft_id)
    if draft.review_status != ExecutiveEmailDraft.ReviewStatus.APPROVED:
        raise ExecutiveBriefBlockedError("Only approved email drafts can request external-send approval.")

    action = "executive_assistant.email_draft.send"
    existing = ApprovalRequest.objects.filter(
        subject_type="executive_assistant.ExecutiveEmailDraft",
        subject_id=str(draft.id),
        action=action,
        status=ApprovalRequest.Status.PENDING,
    ).first()
    if existing:
        return existing

    action_payload = {
        "email_draft_id": str(draft.id),
        "draft_type": draft.draft_type,
        "to_recipients": draft.to_recipients,
        "cc_recipients": draft.cc_recipients,
        "subject": draft.subject,
        "body": draft.body,
        "source_message_id": str(draft.source_message_id) if draft.source_message_id else None,
        "external_send_enabled": False,
        "requires_provider_adapter": True,
    }
    approval = create_approval_request(
        subject_type="executive_assistant.ExecutiveEmailDraft",
        subject_id=str(draft.id),
        subject_version=1,
        action=action,
        action_payload=action_payload,
        requested_by=actor,
        correlation_id=correlation_id,
        expires_at=timezone.now() + timezone.timedelta(hours=expires_in_hours),
        reason_codes=["HUMAN_APPROVAL_REQUIRED_FOR_EXTERNAL_EMAIL"],
    )
    AuditEvent.objects.create(
        actor_type=AuditEvent.ActorType.SYSTEM,
        actor_id=actor,
        action="executive_assistant.email_draft.approval_requested",
        object_type="executive_assistant.ExecutiveEmailDraft",
        object_id=str(draft.id),
        correlation_id=correlation_id,
        metadata={
            "approval_id": str(approval.id),
            "approval_action": approval.action,
            "external_send_enabled": False,
            "requires_provider_adapter": True,
        },
    )
    return approval


def _brief_from_current_state(*, brief_type: str, title: str, source_window: dict) -> dict:
    review = serialize_weekly_review(weekly_review())
    pending_approvals = review["pending_approvals"]
    blocked_tasks = review["blocked_tasks"]
    unverified_tasks = review["unverified_tasks"]
    mock_emails = list(MockEmailMessage.objects.order_by("-created_at")[:10])
    upcoming_events = list(ExecutiveCalendarEvent.objects.exclude(status=ExecutiveCalendarEvent.Status.CANCELLED).order_by("starts_at")[:10])

    agenda_items = []
    if pending_approvals:
        agenda_items.append({"topic": "Pending approvals", "count": len(pending_approvals), "items": pending_approvals})
    if blocked_tasks:
        agenda_items.append({"topic": "Blocked tasks", "count": len(blocked_tasks), "items": blocked_tasks})
    if unverified_tasks:
        agenda_items.append({"topic": "Unverified deliveries", "count": len(unverified_tasks), "items": unverified_tasks})
    if upcoming_events:
        agenda_items.append(
            {
                "topic": "Upcoming calendar events",
                "count": len(upcoming_events),
                "items": [serialize_calendar_event(event) for event in upcoming_events],
            }
        )
    if not agenda_items:
        agenda_items.append({"topic": "Execution check-in", "count": 0, "items": []})

    follow_ups = [
        {"task_id": item["id"], "title": item["title"], "reason": "blocked"}
        for item in blocked_tasks
    ]
    decisions_needed = [
        {
            "approval_id": item["id"],
            "subject_type": item["subject_type"],
            "action": item["action"],
            "expires_at": item["expires_at"],
        }
        for item in pending_approvals
    ]
    inbox_items = [
        {
            "id": str(message.id),
            "sender": message.sender,
            "subject": message.subject,
            "classification": message.classification,
            "proposed_action": message.proposed_action,
        }
        for message in mock_emails
    ]

    summary = (
        f"{title}: {review['counts']['pending_approvals']} pending approvals, "
        f"{review['counts']['blocked_tasks']} blocked tasks, "
        f"{review['counts']['unverified_deliveries']} unverified deliveries, "
        f"{len(inbox_items)} mock inbox items, "
        f"{len(upcoming_events)} upcoming calendar events."
    )
    return {
        "brief_type": brief_type,
        "title": title,
        "source_window": source_window,
        "summary": summary,
        "agenda_items": agenda_items,
        "follow_ups": follow_ups,
        "decisions_needed": decisions_needed,
        "inbox_items": inbox_items,
    }


def create_executive_brief(payload: dict, *, actor_id: str, correlation_id: str) -> ExecutiveBrief:
    brief_type = str(payload.get("brief_type", ExecutiveBrief.BriefType.WEEKLY_REVIEW_PREP)).strip()
    title = str(payload.get("title", "Executive Assistant Brief")).strip()
    source_window = payload.get("source_window", {})

    if brief_type not in ExecutiveBrief.BriefType.values:
        raise InvalidExecutiveBriefPayloadError("brief_type must be WEEKLY_REVIEW_PREP, FOLLOW_UPS or INBOX_TRIAGE.")
    if not title:
        raise InvalidExecutiveBriefPayloadError("title is required.")
    if not isinstance(source_window, dict):
        raise InvalidExecutiveBriefPayloadError("source_window must be an object.")

    data = _brief_from_current_state(brief_type=brief_type, title=title, source_window=source_window)
    actor = actor_id.strip() or "api"
    with transaction.atomic():
        brief = ExecutiveBrief.objects.create(
            brief_type=data["brief_type"],
            title=data["title"],
            source_window=data["source_window"],
            summary=data["summary"],
            agenda_items=data["agenda_items"],
            follow_ups=data["follow_ups"],
            decisions_needed=data["decisions_needed"],
            inbox_items=data["inbox_items"],
            status=ExecutiveBrief.Status.READY,
            no_external_send=True,
            created_by=actor,
        )
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="executive_assistant.brief.created",
            object_type="executive_assistant.ExecutiveBrief",
            object_id=str(brief.id),
            correlation_id=correlation_id,
            metadata={
                "brief_type": brief.brief_type,
                "agenda_items": len(brief.agenda_items),
                "follow_ups": len(brief.follow_ups),
                "decisions_needed": len(brief.decisions_needed),
                "inbox_items": len(brief.inbox_items),
                "no_external_send": True,
            },
        )
    return brief


def propose_tasks_from_brief(payload: dict, *, brief_id: str, actor_id: str, correlation_id: str) -> list[ExecutiveBriefTaskProposal]:
    objective_id = str(payload.get("objective_id", "")).strip()
    if not objective_id:
        raise InvalidExecutiveBriefPayloadError("objective_id is required.")
    actor = actor_id.strip() or "api"

    with transaction.atomic():
        brief = ExecutiveBrief.objects.select_for_update().get(id=brief_id)
        if brief.status != ExecutiveBrief.Status.READY:
            raise ExecutiveBriefBlockedError("Only ready briefs can propose tasks.")
        if not brief.follow_ups:
            raise ExecutiveBriefBlockedError("Brief has no follow-ups to propose as tasks.")

        proposals: list[ExecutiveBriefTaskProposal] = []
        for index, follow_up in enumerate(brief.follow_ups):
            if not isinstance(follow_up, dict):
                continue
            source_task_id = str(follow_up.get("task_id", "")).strip()
            source_title = str(follow_up.get("title", "")).strip()
            reason = str(follow_up.get("reason", "follow_up")).strip() or "follow_up"
            if not source_title:
                continue

            external_key = f"executive-brief:{brief.id}:follow-up:{index}"
            task, _created = upsert_task(
                {
                    "objective_id": objective_id,
                    "external_key": external_key,
                    "title": f"Follow up: {source_title}",
                    "business_outcome": f"Resolve executive follow-up from brief {brief.id}.",
                    "acceptance_criteria": [
                        {
                            "description": f"Follow-up is resolved or explicitly reclassified: {source_title}",
                            "criterion_type": AcceptanceCriterion.CriterionType.MANUAL,
                            "required": True,
                        }
                    ],
                },
                actor_id=actor,
                correlation_id=correlation_id,
            )
            if task.owner_agent_id != "executive_assistant":
                task.owner_agent_id = "executive_assistant"
                task.save(update_fields=["owner_agent_id", "updated_at"])
            proposal, _proposal_created = ExecutiveBriefTaskProposal.objects.get_or_create(
                brief=brief,
                follow_up_index=index,
                defaults={
                    "task_id": task.id,
                    "external_key": external_key,
                    "title": task.title,
                    "status": task.status,
                    "review_status": ExecutiveBriefTaskProposal.ReviewStatus.PENDING,
                    "no_external_send": True,
                    "created_by": actor,
                },
            )
            if proposal.task_id != task.id or proposal.status != task.status or proposal.title != task.title:
                proposal.task_id = task.id
                proposal.status = task.status
                proposal.title = task.title
                proposal.save(update_fields=["task_id", "status", "title"])
            proposals.append(proposal)

        if not proposals:
            raise ExecutiveBriefBlockedError("Brief follow-ups did not contain taskable items.")

        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="executive_assistant.tasks.proposed",
            object_type="executive_assistant.ExecutiveBrief",
            object_id=str(brief.id),
            correlation_id=correlation_id,
            metadata={
                "objective_id": objective_id,
                "task_count": len(proposals),
                "no_external_send": True,
            },
        )
    return proposals


def archive_executive_brief(*, brief_id: str, actor_id: str, correlation_id: str) -> ExecutiveBrief:
    actor = actor_id.strip() or "api"
    with transaction.atomic():
        brief = ExecutiveBrief.objects.select_for_update().get(id=brief_id)
        if brief.status != ExecutiveBrief.Status.READY:
            raise ExecutiveBriefBlockedError("Only ready briefs can be archived.")
        brief.status = ExecutiveBrief.Status.ARCHIVED
        brief.save(update_fields=["status"])
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="executive_assistant.brief.archived",
            object_type="executive_assistant.ExecutiveBrief",
            object_id=str(brief.id),
            correlation_id=correlation_id,
            metadata={
                "brief_type": brief.brief_type,
                "no_external_send": True,
            },
        )
    return brief


def review_task_proposal(payload: dict, *, proposal_id: str, actor_id: str, correlation_id: str) -> ExecutiveBriefTaskProposal:
    decision = str(payload.get("decision", "")).strip()
    if decision not in {ExecutiveBriefTaskProposal.ReviewStatus.ACCEPTED, ExecutiveBriefTaskProposal.ReviewStatus.DISMISSED}:
        raise InvalidExecutiveBriefPayloadError("decision must be ACCEPTED or DISMISSED.")
    review_note = str(payload.get("review_note", "")).strip()

    actor = actor_id.strip() or "api"
    with transaction.atomic():
        proposal = ExecutiveBriefTaskProposal.objects.select_for_update().get(id=proposal_id)
        if proposal.review_status != ExecutiveBriefTaskProposal.ReviewStatus.PENDING:
            raise ExecutiveBriefBlockedError("Only pending task proposals can be reviewed.")

        task = Task.objects.select_for_update().get(id=proposal.task_id)
        if decision == ExecutiveBriefTaskProposal.ReviewStatus.ACCEPTED:
            if task.status == Task.Status.DRAFT:
                task = transition_task(
                    str(task.id),
                    to_status=Task.Status.PLANNED,
                    expected_version=task.version,
                    actor_id=actor,
                    correlation_id=correlation_id,
                )
        else:
            if task.status == Task.Status.DRAFT:
                task = transition_task(
                    str(task.id),
                    to_status=Task.Status.CANCELLED,
                    expected_version=task.version,
                    actor_id=actor,
                    correlation_id=correlation_id,
                )

        proposal.review_status = decision
        proposal.status = task.status
        proposal.reviewed_by = actor
        proposal.reviewed_at = timezone.now()
        proposal.review_note = review_note
        proposal.save(update_fields=["review_status", "status", "reviewed_by", "reviewed_at", "review_note"])

        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="executive_assistant.task_proposal.reviewed",
            object_type="executive_assistant.ExecutiveBriefTaskProposal",
            object_id=str(proposal.id),
            correlation_id=correlation_id,
            metadata={
                "task_id": str(task.id),
                "decision": decision,
                "task_status": task.status,
                "review_note_present": bool(review_note),
                "no_external_send": True,
            },
        )
    return proposal
