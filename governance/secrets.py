import os
import re

from django.db import transaction

from governance.models import AuditEvent, SecretReference


SECRET_VALUE_KEYS = {
    "access_token",
    "refresh_token",
    "client_secret",
    "password",
    "oauth_token",
    "token",
    "secret",
    "private_key",
    "authorization",
    "value",
}


class SecretReferenceError(Exception):
    code = "SECRET_REFERENCE_ERROR"


class InvalidSecretReferenceError(SecretReferenceError):
    code = "INVALID_SECRET_REFERENCE"


class SecretNotConfiguredError(SecretReferenceError):
    code = "SECRET_NOT_CONFIGURED"


def serialize_secret_reference(reference: SecretReference) -> dict:
    return {
        "id": str(reference.id),
        "name": reference.name,
        "purpose": reference.purpose,
        "provider": reference.provider,
        "env_var_name": reference.env_var_name,
        "active": reference.active,
        "configured": bool(os.environ.get(reference.env_var_name, "").strip()),
        "stores_secret_value": False,
        "created_by": reference.created_by,
        "created_at": reference.created_at.isoformat(),
    }


def create_secret_reference(payload: dict, *, actor_id: str, correlation_id: str) -> SecretReference:
    if SECRET_VALUE_KEYS.intersection({str(key).lower() for key in payload}):
        raise InvalidSecretReferenceError("Secret references cannot store token, password, or secret values.")
    name = str(payload.get("name", "")).strip()
    purpose = str(payload.get("purpose", "")).strip()
    provider = str(payload.get("provider", "")).strip().lower()
    env_var_name = str(payload.get("env_var_name", "")).strip()
    if not name or not provider or not env_var_name:
        raise InvalidSecretReferenceError("name, purpose, provider and env_var_name are required.")
    if purpose not in SecretReference.Purpose.values:
        raise InvalidSecretReferenceError("purpose must be OAUTH_READ_ONLY, OAUTH_REFRESH or GITHUB_ISSUE_CREATE.")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,79}", env_var_name):
        raise InvalidSecretReferenceError("env_var_name must name an environment variable, not contain a secret.")
    actor = actor_id.strip() or "api"
    with transaction.atomic():
        reference = SecretReference.objects.create(
            name=name,
            purpose=purpose,
            provider=provider,
            env_var_name=env_var_name,
            created_by=actor,
        )
        AuditEvent.objects.create(
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id=actor,
            action="governance.secret_reference.created",
            object_type="governance.SecretReference",
            object_id=str(reference.id),
            correlation_id=correlation_id,
            metadata={
                "name": reference.name,
                "purpose": reference.purpose,
                "provider": reference.provider,
                "env_var_name": reference.env_var_name,
                "stores_secret_value": False,
            },
        )
    return reference


def resolve_secret_value(*, name: str, purpose: str, provider: str) -> str:
    try:
        reference = SecretReference.objects.get(name=name, purpose=purpose, provider=provider.strip().lower(), active=True)
    except SecretReference.DoesNotExist as exc:
        raise SecretNotConfiguredError("Active secret reference was not found.") from exc
    value = os.environ.get(reference.env_var_name, "").strip()
    if not value:
        raise SecretNotConfiguredError(f"Environment variable {reference.env_var_name} is not set.")
    return value
