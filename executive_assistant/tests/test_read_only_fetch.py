import json

import pytest

from executive_assistant.models import ExecutiveCalendarEvent, ExecutiveProviderSyncConfig
from governance.models import SecretReference
from mailbox.models import MockEmailMessage


pytestmark = pytest.mark.django_db


def headers(key: str) -> dict:
    return {"Idempotency-Key": key, "X-Correlation-ID": f"corr-{key}", "X-Actor-ID": "executive_assistant"}


def test_secret_reference_rejects_raw_token_and_does_not_store_a_value(client):
    rejected = client.post(
        "/api/v1/secrets/references/create/",
        data=json.dumps({
            "name": "gmail-read",
            "purpose": "OAUTH_READ_ONLY",
            "provider": "gmail",
            "env_var_name": "SHARONS_GMAIL_TOKEN",
            "access_token": "should-not-be-stored",
        }),
        content_type="application/json",
        headers=headers("secret-reject"),
    )
    assert rejected.status_code == 400
    assert SecretReference.objects.count() == 0

    created = client.post(
        "/api/v1/secrets/references/create/",
        data=json.dumps({
            "name": "gmail-read",
            "purpose": "OAUTH_READ_ONLY",
            "provider": "gmail",
            "env_var_name": "SHARONS_GMAIL_TOKEN",
        }),
        content_type="application/json",
        headers=headers("secret-create"),
    )
    assert created.status_code == 201
    body = created.json()["secret_reference"]
    assert body["stores_secret_value"] is False
    assert body["configured"] is False
    assert "should-not-be-stored" not in json.dumps(body)


def test_read_only_fetch_does_not_call_provider_without_a_configured_secret(client, monkeypatch):
    SecretReference.objects.create(
        name="gmail-read",
        purpose=SecretReference.Purpose.OAUTH_READ_ONLY,
        provider="gmail",
        env_var_name="SHARONS_GMAIL_TOKEN",
        created_by="executive_assistant",
    )
    config = ExecutiveProviderSyncConfig.objects.create(
        provider_type=ExecutiveProviderSyncConfig.ProviderType.EMAIL,
        provider_name="gmail",
        source="gmail_readonly",
        status=ExecutiveProviderSyncConfig.Status.READY_FOR_CONNECTOR,
        scopes=["gmail.readonly"],
        config={"oauth_reference": "gmail-read"},
        created_by="executive_assistant",
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("provider was contacted")

    monkeypatch.setattr("executive_assistant.provider_http.http_json", fail_if_called)
    monkeypatch.delenv("SHARONS_GMAIL_TOKEN", raising=False)

    response = client.post(
        f"/api/v1/executive-assistant/provider-sync-configs/{config.id}/fetch/",
        data=json.dumps({"limit": 5}),
        content_type="application/json",
        headers=headers("fetch-missing-secret"),
    )

    assert response.status_code == 409
    assert MockEmailMessage.objects.count() == 0


def test_read_only_fetch_ingests_gmail_metadata_and_does_not_send(client, monkeypatch):
    monkeypatch.setenv("SHARONS_GMAIL_TOKEN", "test-token")
    SecretReference.objects.create(
        name="gmail-read",
        purpose=SecretReference.Purpose.OAUTH_READ_ONLY,
        provider="gmail",
        env_var_name="SHARONS_GMAIL_TOKEN",
        created_by="executive_assistant",
    )
    config = ExecutiveProviderSyncConfig.objects.create(
        provider_type=ExecutiveProviderSyncConfig.ProviderType.EMAIL,
        provider_name="gmail",
        source="gmail_readonly",
        status=ExecutiveProviderSyncConfig.Status.READY_FOR_CONNECTOR,
        scopes=["gmail.readonly"],
        config={"oauth_reference": "gmail-read"},
        created_by="executive_assistant",
    )
    calls = []

    def fake_http(method, url, *, token, payload=None):
        calls.append((method, url, token, payload))
        if url.endswith("maxResults=5"):
            return {"messages": [{"id": "msg1"}]}
        return {"snippet": "Read only note", "payload": {"headers": [{"name": "Subject", "value": "Beta note"}, {"name": "From", "value": "User Name <user@example.com>"}]}}

    monkeypatch.setattr("executive_assistant.provider_http.http_json", fake_http)

    response = client.post(
        f"/api/v1/executive-assistant/provider-sync-configs/{config.id}/fetch/",
        data=json.dumps({"limit": 5}),
        content_type="application/json",
        headers=headers("fetch-gmail"),
    )

    assert response.status_code == 200
    assert response.json()["will_send_email"] is False
    assert calls[0][0] == "GET"
    assert all(call[0] == "GET" for call in calls)
    message = MockEmailMessage.objects.get()
    assert message.subject == "Beta note"
    assert message.sender == "user@example.com"
    assert ExecutiveCalendarEvent.objects.count() == 0


def test_read_only_fetch_refuses_send_scopes(client, monkeypatch):
    monkeypatch.setenv("SHARONS_GMAIL_TOKEN", "test-token")
    SecretReference.objects.create(
        name="gmail-read",
        purpose=SecretReference.Purpose.OAUTH_READ_ONLY,
        provider="gmail",
        env_var_name="SHARONS_GMAIL_TOKEN",
        created_by="executive_assistant",
    )
    config = ExecutiveProviderSyncConfig.objects.create(
        provider_type=ExecutiveProviderSyncConfig.ProviderType.EMAIL,
        provider_name="gmail",
        source="gmail_readonly",
        status=ExecutiveProviderSyncConfig.Status.READY_FOR_CONNECTOR,
        scopes=["gmail.send"],
        config={"oauth_reference": "gmail-read"},
        created_by="executive_assistant",
    )
    monkeypatch.setattr("executive_assistant.provider_http.http_json", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("called")))

    response = client.post(
        f"/api/v1/executive-assistant/provider-sync-configs/{config.id}/fetch/",
        data=json.dumps({}),
        content_type="application/json",
        headers=headers("fetch-send-scope"),
    )

    assert response.status_code == 409
    assert MockEmailMessage.objects.count() == 0
