from django.db import transaction

from governance.models import AuditEvent
from operations.models import AgentDefinition, Evidence, Task
from operations.services import verify_task
from qa.models import VerificationReview


class QaError(Exception):
    code = "QA_ERROR"


class InvalidQaPayloadError(QaError):
    code = "INVALID_QA_PAYLOAD"


class QaBlockedError(QaError):
    code = "QA_BLOCKED"


def serialize_verification_review(review: VerificationReview) -> dict:
    return {
        "id": str(review.id),
        "task_id": str(review.task_id),
        "decision": review.decision,
        "notes": review.notes,
        "evidence_ids": review.evidence_ids,
        "no_external_action": review.no_external_action,
        "reviewed_by": review.reviewed_by,
        "created_at": review.created_at.isoformat(),
    }


def qa_status() -> dict:
    return {
        "agent_id": "qa",
        "agent_registered": AgentDefinition.objects.filter(agent_id="qa", active=True).exists(),
        "external_action_enabled": False,
        "verification_queue": Task.objects.filter(status=Task.Status.DELIVERED_UNVERIFIED).count(),
        "reviews": VerificationReview.objects.count(),
        "accepted_reviews": VerificationReview.objects.filter(decision=VerificationReview.Decision.ACCEPTED).count(),
    }


def list_verification_queue(*, limit: int = 100) -> list[Task]:
    return list(Task.objects.filter(status=Task.Status.DELIVERED_UNVERIFIED).select_related("objective").order_by("-updated_at")[:limit])


def review_task_evidence(payload: dict, *, task_id: str, actor_id: str, correlation_id: str) -> VerificationReview:
    decision = str(payload.get("decision", "")).strip()
    notes = str(payload.get("notes", "")).strip()
    mark_passed = bool(payload.get("mark_passed", decision == VerificationReview.Decision.ACCEPTED))
    if decision not in VerificationReview.Decision.values:
        raise InvalidQaPayloadError("decision must be ACCEPTED, REJECTED or NEEDS_MORE_EVIDENCE.")
    actor = actor_id.strip() or "qa_agent"
    with transaction.atomic():
        task = Task.objects.select_for_update().get(id=task_id)
        if task.status != Task.Status.DELIVERED_UNVERIFIED:
            raise QaBlockedError("QA reviews require a DELIVERED_UNVERIFIED task.")
        evidence = list(task.evidence.select_for_update().order_by("created_at"))
        if decision == VerificationReview.Decision.ACCEPTED and not evidence:
            raise QaBlockedError("Accepted QA review requires at least one evidence record.")
        evidence_ids = [str(item.id) for item in evidence]
        if decision == VerificationReview.Decision.ACCEPTED:
            for item in evidence:
                if not item.verified:
                    item.verified = True
                    item.save(update_fields=["verified"])

        review = VerificationReview.objects.create(
            task=task,
            decision=decision,
            notes=notes,
            evidence_ids=evidence_ids,
            reviewed_by=actor,
            no_external_action=True,
        )

        if decision == VerificationReview.Decision.ACCEPTED:
            verify_task(
                {"mark_passed": mark_passed, "notes": notes},
                task_id=str(task.id),
                actor_id=actor,
                correlation_id=correlation_id,
            )

        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="qa.verification_review.created",
            object_type="qa.VerificationReview",
            object_id=str(review.id),
            correlation_id=correlation_id,
            metadata={
                "task_id": str(task.id),
                "decision": decision,
                "evidence_count": len(evidence_ids),
                "no_external_action": True,
            },
        )
    return review

