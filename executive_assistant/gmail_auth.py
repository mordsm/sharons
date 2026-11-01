import os

from governance.models import SecretReference
from governance.secrets import SecretNotConfiguredError, resolve_secret_value

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_CLIENT_ID_ENV = "SHARONS_GMAIL_CLIENT_ID"
GMAIL_CLIENT_SECRET_ENV = "SHARONS_GMAIL_CLIENT_SECRET"


def gmail_access_token(config) -> str:
    """Return a Gmail bearer token. Refresh when a refresh reference and client credentials exist."""
    refreshed = _refreshed_access_token(config)
    if refreshed:
        return refreshed
    reference_name = str(config.config.get("oauth_reference", "")).strip()
    if not reference_name:
        raise SecretNotConfiguredError("Gmail needs an access-token reference or a refresh-token reference.")
    return resolve_secret_value(name=reference_name, purpose="OAUTH_READ_ONLY", provider="gmail")


def _refreshed_access_token(config) -> str:
    refresh_name = str(config.config.get("oauth_refresh_reference", "")).strip()
    if not refresh_name:
        return ""
    if not SecretReference.objects.filter(
        name=refresh_name,
        purpose=SecretReference.Purpose.OAUTH_REFRESH,
        provider="gmail",
        active=True,
    ).exists():
        return ""
    client_id = os.environ.get(GMAIL_CLIENT_ID_ENV, "").strip()
    client_secret = os.environ.get(GMAIL_CLIENT_SECRET_ENV, "").strip()
    if not client_id or not client_secret:
        return ""
    refresh_token = resolve_secret_value(name=refresh_name, purpose="OAUTH_REFRESH", provider="gmail")
    from executive_assistant.provider_http import http_form

    response = http_form(
        GOOGLE_TOKEN_URL,
        {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
    )
    access_token = str(response.get("access_token", "")).strip()
    if not access_token:
        raise SecretNotConfiguredError("Google did not return an access token.")
    return access_token
