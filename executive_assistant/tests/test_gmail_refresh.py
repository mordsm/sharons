import json

import pytest
from django.core.management import call_command

from executive_assistant.models import ExecutiveProviderSyncConfig
from governance.models import SecretReference
from mailbox.models import MockEmailMessage


pytestmark = pytest.mark.django_db


def headers(key: str) -> dict:
    return {"Idempotency-Key": key, "X-Correlation-ID": f"corr-{key}", "X-Actor-ID": "executive_assistant"}


def test_register_connector_secrets_is_idempotent_and_stores_no_values():
    call_command("register_connector_secrets")
    call_command("register_connector_secrets")

    assert SecretReference.objects.count() == 3
    names = set(SecretReference.objects.values_list("env_var_name", flat=True))
    assert names == {"SHARONS_GMAIL_TOKEN", "SHARONS_GMAIL_REFRESH_TOKEN", "SHARONS_GITHUB_TOKEN"}
    config = ExecutiveProviderSyncConfig.objects.get(provider_name="gmail", source="gmail_readonly")
    assert config.config["oauth_refresh_reference"] == "gmail-refresh"
    assert config.no_external_action is True
    assert "access_token" not in config.config


def test_gmail_fetch_refreshes_access_token_and_does_not_record_it(client, monkeypatch):
    call_command("register_connector_secrets")
    monkeypatch.setenv("SHARONS_GMAIL_REFRESH_TOKEN", "refresh-secret")
    monkeypatch.setenv("SHARONS_GMAIL_CLIENT_ID", "client-id")
    monkeypatch.setenv("SHARONS_GMAIL_CLIENT_SECRET", "client-secret")
    monkeypatch.delenv("SHARONS_GMAIL_TOKEN", raising=False)
    seen = []

    def fake_form(url, form):
        seen.append(("refresh", url, form["grant_type"]))
        assert form["refresh_token"] == "refresh-secret"
        return {"access_token": "fresh-access", "expires_in": 3600}

    def fake_http(method, url, *, token, payload=None):
        seen.append(("get", method, token))
        if "maxResults" in url:
            return {"messages": [{"id": "abc"}]}
        return {"snippet": "hello", "payload": {"headers": [{"name": "Subject", "value": "Inbox"}, {"name": "From", "value": "a@example.com"}]}}

    monkeypatch.setattr("executive_assistant.provider_http.http_form", fake_form)
    monkeypatch.setattr("executive_assistant.provider_http.http_json", fake_http)
    config = ExecutiveProviderSyncConfig.objects.get(source="gmail_readonly")

    response = client.post(
        f"/api/v1/executive-assistant/provider-sync-configs/{config.id}/fetch/",
        data=json.dumps({"limit": 1}),
        content_type="application/json",
        headers=headers("gmail-refresh"),
    )

    assert response.status_code == 200
    assert ("refresh", "https://oauth2.googleapis.com/token", "refresh_token") in seen
    assert ("get", "GET", "fresh-access") in seen
    assert "refresh-secret" not in json.dumps(response.json())
    assert MockEmailMessage.objects.get().subject == "Inbox"
