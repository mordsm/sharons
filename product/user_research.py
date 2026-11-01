from django.db import transaction

from governance.models import AuditEvent
from portfolio.models import ProjectConnection
from product.models import (
    ProductSpecContract,
    UserResearchContract,
    UserResearchFinding,
    UserResearchInterview,
    UserResearchQuestion,
)
from product.services import InvalidProductContractPayloadError, ProductContractBlockedError


CONTACT_FIELD_KEYS = {
    "email",
    "phone",
    "participant_email",
    "participant_phone",
    "participant_name",
    "contact_email",
    "contact_person",
    "schedule_interview",
    "outreach",
    "customer_email",
}


def reject_customer_contact(payload: dict) -> None:
    if payload.get("contact_customer") is True or payload.get("no_customer_contact") is False:
        raise ProductContractBlockedError("User research artifacts cannot contact a customer.")
    for key in CONTACT_FIELD_KEYS:
        value = payload.get(key)
        if value not in (None, "", [], {}):
            raise ProductContractBlockedError("User research artifacts cannot store a direct contact channel.")


def _looks_like_contact(value: str) -> bool:
    text = value.strip().lower()
    return "@" in text or text.startswith("+") or text.startswith("http://") or text.startswith("https://")


def serialize_user_research_interview(interview: UserResearchInterview) -> dict:
    return {
        "id": str(interview.id),
        "contract_id": str(interview.contract_id),
        "label": interview.label,
        "segment": interview.segment,
        "summary": interview.summary,
        "observations": interview.observations,
        "no_customer_contact": interview.no_customer_contact,
        "created_by": interview.created_by,
        "created_at": interview.created_at.isoformat(),
    }


def serialize_user_research_finding(finding: UserResearchFinding) -> dict:
    return {
        "id": str(finding.id),
        "contract_id": str(finding.contract_id),
        "interview_id": str(finding.interview_id) if finding.interview_id else None,
        "statement": finding.statement,
        "evidence_note": finding.evidence_note,
        "confidence": finding.confidence,
        "related_requirement_id": finding.related_requirement_id,
        "no_customer_contact": finding.no_customer_contact,
        "created_by": finding.created_by,
        "created_at": finding.created_at.isoformat(),
    }


def serialize_user_research_question(question: UserResearchQuestion) -> dict:
    return {
        "id": str(question.id),
        "contract_id": str(question.contract_id),
        "question": question.question,
        "status": question.status,
        "resolution_note": question.resolution_note,
        "no_customer_contact": question.no_customer_contact,
        "created_by": question.created_by,
        "created_at": question.created_at.isoformat(),
        "updated_at": question.updated_at.isoformat(),
    }


def serialize_user_research_contract(contract: UserResearchContract) -> dict:
    return {
        "id": str(contract.id),
        "spec_contract_id": str(contract.spec_contract_id),
        "project_id": str(contract.spec_contract.project_id),
        "title": contract.title,
        "research_question": contract.research_question,
        "method": contract.method,
        "participant_segment": contract.participant_segment,
        "status": contract.status,
        "no_customer_contact": contract.no_customer_contact,
        "no_external_write": contract.no_external_write,
        "interviews": [serialize_user_research_interview(item) for item in contract.interviews.all()],
        "findings": [serialize_user_research_finding(item) for item in contract.findings.all()],
        "questions": [serialize_user_research_question(item) for item in contract.questions.all()],
        "created_by": contract.created_by,
        "created_at": contract.created_at.isoformat(),
    }


def _lock_open_research_spec(spec_contract_id: str) -> ProductSpecContract:
    spec = ProductSpecContract.objects.select_for_update().select_related("project_connection", "project").get(id=spec_contract_id)
    if spec.status == ProductSpecContract.Status.CANCELLED:
        raise ProductContractBlockedError("User research requires a product spec that is not cancelled.")
    if spec.project_connection.permission_mode != ProjectConnection.PermissionMode.READ_ONLY or not spec.no_external_write:
        raise ProductContractBlockedError("User research requires a read-only product spec.")
    return spec


def create_user_research_contract(payload: dict, *, spec_contract_id: str, actor_id: str, correlation_id: str) -> UserResearchContract:
    reject_customer_contact(payload)
    title = str(payload.get("title", "")).strip()
    research_question = str(payload.get("research_question", "")).strip()
    method = str(payload.get("method", UserResearchContract.Method.INTERVIEW_NOTES)).strip()
    participant_segment = str(payload.get("participant_segment", "")).strip()
    if not title or not research_question:
        raise InvalidProductContractPayloadError("title and research_question are required.")
    if method not in UserResearchContract.Method.values:
        raise InvalidProductContractPayloadError("method must be INTERVIEW_NOTES, USABILITY_NOTES, SUPPORT_NOTES or INTERNAL_SYNTHESIS.")
    if _looks_like_contact(participant_segment):
        raise ProductContractBlockedError("Participant segment must be a cohort label, not a contact channel.")

    actor = actor_id.strip() or "api"
    with transaction.atomic():
        spec = _lock_open_research_spec(spec_contract_id)
        contract = UserResearchContract.objects.create(
            spec_contract=spec,
            title=title,
            research_question=research_question,
            method=method,
            participant_segment=participant_segment,
            created_by=actor,
        )
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="product.user_research.created",
            object_type="product.UserResearchContract",
            object_id=str(contract.id),
            correlation_id=correlation_id,
            metadata={
                "spec_contract_id": str(spec.id),
                "project_id": str(spec.project_id),
                "method": contract.method,
                "no_customer_contact": True,
                "no_external_write": True,
            },
        )
    return contract


def list_user_research_contracts(*, spec_contract_id: str) -> list[UserResearchContract]:
    return list(
        UserResearchContract.objects.filter(spec_contract_id=spec_contract_id)
        .select_related("spec_contract")
        .prefetch_related("interviews", "findings", "questions")
    )


def _lock_research_contract(contract_id: str) -> UserResearchContract:
    contract = UserResearchContract.objects.select_for_update().select_related("spec_contract__project_connection").get(id=contract_id)
    if contract.status == UserResearchContract.Status.CLOSED:
        raise ProductContractBlockedError("Closed user research contracts cannot accept new artifacts.")
    if contract.spec_contract.status == ProductSpecContract.Status.CANCELLED:
        raise ProductContractBlockedError("User research requires a product spec that is not cancelled.")
    return contract


def add_user_research_interview(payload: dict, *, contract_id: str, actor_id: str, correlation_id: str) -> UserResearchInterview:
    reject_customer_contact(payload)
    label = str(payload.get("label", "")).strip()
    segment = str(payload.get("segment", "")).strip()
    summary = str(payload.get("summary", "")).strip()
    observations = payload.get("observations", [])
    if not label or not summary:
        raise InvalidProductContractPayloadError("label and summary are required.")
    if not isinstance(observations, list) or not all(str(item).strip() for item in observations):
        raise InvalidProductContractPayloadError("observations must be a list of non-empty strings.")
    if _looks_like_contact(label) or _looks_like_contact(segment):
        raise ProductContractBlockedError("Interview labels must stay cohort labels, not contact channels.")

    actor = actor_id.strip() or "api"
    with transaction.atomic():
        contract = _lock_research_contract(contract_id)
        interview = UserResearchInterview.objects.create(
            contract=contract,
            label=label,
            segment=segment,
            summary=summary,
            observations=[str(item).strip() for item in observations],
            created_by=actor,
        )
        if contract.status == UserResearchContract.Status.OPEN:
            contract.status = UserResearchContract.Status.IN_REVIEW
            contract.save(update_fields=["status"])
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="product.user_research.interview_added",
            object_type="product.UserResearchInterview",
            object_id=str(interview.id),
            correlation_id=correlation_id,
            metadata={"contract_id": str(contract.id), "no_customer_contact": True},
        )
    return interview


def add_user_research_finding(payload: dict, *, contract_id: str, actor_id: str, correlation_id: str) -> UserResearchFinding:
    reject_customer_contact(payload)
    statement = str(payload.get("statement", "")).strip()
    evidence_note = str(payload.get("evidence_note", "")).strip()
    confidence = str(payload.get("confidence", UserResearchFinding.Confidence.LOW)).strip()
    related_requirement_id = str(payload.get("related_requirement_id", "")).strip()
    interview_id = str(payload.get("interview_id", "")).strip()
    if not statement:
        raise InvalidProductContractPayloadError("statement is required.")
    if confidence not in UserResearchFinding.Confidence.values:
        raise InvalidProductContractPayloadError("confidence must be LOW, MEDIUM or HIGH.")

    actor = actor_id.strip() or "api"
    with transaction.atomic():
        contract = _lock_research_contract(contract_id)
        interview = None
        if interview_id:
            interview = UserResearchInterview.objects.select_for_update().get(id=interview_id, contract=contract)
        finding = UserResearchFinding.objects.create(
            contract=contract,
            interview=interview,
            statement=statement,
            evidence_note=evidence_note,
            confidence=confidence,
            related_requirement_id=related_requirement_id,
            created_by=actor,
        )
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="product.user_research.finding_added",
            object_type="product.UserResearchFinding",
            object_id=str(finding.id),
            correlation_id=correlation_id,
            metadata={"contract_id": str(contract.id), "confidence": finding.confidence, "no_customer_contact": True},
        )
    return finding


def add_user_research_question(payload: dict, *, contract_id: str, actor_id: str, correlation_id: str) -> UserResearchQuestion:
    reject_customer_contact(payload)
    question_text = str(payload.get("question", "")).strip()
    if not question_text:
        raise InvalidProductContractPayloadError("question is required.")

    actor = actor_id.strip() or "api"
    with transaction.atomic():
        contract = _lock_research_contract(contract_id)
        question = UserResearchQuestion.objects.create(contract=contract, question=question_text, created_by=actor)
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="product.user_research.question_added",
            object_type="product.UserResearchQuestion",
            object_id=str(question.id),
            correlation_id=correlation_id,
            metadata={"contract_id": str(contract.id), "no_customer_contact": True},
        )
    return question


def update_user_research_question(payload: dict, *, question_id: str, actor_id: str, correlation_id: str) -> UserResearchQuestion:
    reject_customer_contact(payload)
    status = str(payload.get("status", "")).strip()
    resolution_note = str(payload.get("resolution_note", "")).strip()
    if status not in UserResearchQuestion.Status.values:
        raise InvalidProductContractPayloadError("status must be OPEN, DEFERRED or RESOLVED.")
    if status in {UserResearchQuestion.Status.DEFERRED, UserResearchQuestion.Status.RESOLVED} and not resolution_note:
        raise InvalidProductContractPayloadError("resolution_note is required when a question is deferred or resolved.")

    actor = actor_id.strip() or "api"
    with transaction.atomic():
        question = UserResearchQuestion.objects.select_for_update().select_related("contract").get(id=question_id)
        if question.contract.status == UserResearchContract.Status.CLOSED and status != question.status:
            raise ProductContractBlockedError("Closed user research contracts cannot change question status.")
        question.status = status
        question.resolution_note = resolution_note
        question.save(update_fields=["status", "resolution_note", "updated_at"])
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="product.user_research.question_updated",
            object_type="product.UserResearchQuestion",
            object_id=str(question.id),
            correlation_id=correlation_id,
            metadata={"contract_id": str(question.contract_id), "status": question.status, "no_customer_contact": True},
        )
    return question
