from dataclasses import dataclass

from executive_assistant.models import ExecutiveProviderSyncConfig


class ReadOnlyConnectorAdapterError(Exception):
    """Raised when a provider adapter would need unavailable external access."""


def _email_address(value: str) -> str:
    from email.utils import parseaddr

    from django.core.exceptions import ValidationError
    from django.core.validators import validate_email

    _, address = parseaddr(value or "")
    address = address.strip()
    try:
        validate_email(address)
    except ValidationError:
        return ""
    return address


@dataclass(frozen=True)
class ConnectorPreflight:
    connector_key: str
    provider_name: str
    provider_type: str
    adapter_available: bool
    oauth_configured: bool
    external_action_enabled: bool
    dry_run_only: bool
    blockers: list[str]
    warnings: list[str]

    def as_dict(self) -> dict:
        return {
            "connector_key": self.connector_key,
            "provider_name": self.provider_name,
            "provider_type": self.provider_type,
            "adapter_available": self.adapter_available,
            "oauth_configured": self.oauth_configured,
            "external_action_enabled": self.external_action_enabled,
            "dry_run_only": self.dry_run_only,
            "blockers": self.blockers,
            "warnings": self.warnings,
        }


class ReadOnlyConnectorAdapter:
    connector_key = "read_only_adapter"
    provider_name = "generic"
    provider_type = ""
    source_markers: tuple[str, ...] = ()
    required_scope_markers: tuple[str, ...] = ()
    planned_read_model = "provider_records"
    adapter_available = False
    oauth_configured = False

    def fetch_records(self, config: ExecutiveProviderSyncConfig, *, limit: int = 25) -> list[dict]:
        raise ReadOnlyConnectorAdapterError("Real provider access is not enabled for this connector.")


class DisabledReadOnlyConnector(ReadOnlyConnectorAdapter):
    connector_key = "disabled_read_only"
    provider_name = "generic"
    provider_type = ""

    def matches(self, config: ExecutiveProviderSyncConfig) -> bool:
        provider_name = config.provider_name.lower()
        source = config.source.lower()
        provider_matches = self.provider_name in provider_name or any(marker in provider_name for marker in self.source_markers)
        source_matches = any(marker in source for marker in self.source_markers)
        return config.provider_type == self.provider_type and (provider_matches or source_matches)

    def preflight(self, config: ExecutiveProviderSyncConfig) -> ConnectorPreflight:
        warnings = []
        scopes = [str(scope).lower() for scope in config.scopes]
        if self.required_scope_markers and not any(
            marker in scope for marker in self.required_scope_markers for scope in scopes
        ):
            warnings.append("Expected read-only provider scope marker is not recorded.")
        return ConnectorPreflight(
            connector_key=self.connector_key,
            provider_name=self.provider_name,
            provider_type=self.provider_type,
            adapter_available=self.adapter_available,
            oauth_configured=self.oauth_configured,
            external_action_enabled=False,
            dry_run_only=True,
            blockers=[],
            warnings=warnings,
        )

    def dry_run(self, config: ExecutiveProviderSyncConfig) -> dict:
        preflight = self.preflight(config)
        return {
            "connector": preflight.as_dict(),
            "attempted_external_connection": False,
            "records_ingested": 0,
            "records_available": 0,
            "message": "Connector dry-run completed without contacting any external provider.",
        }

    def sync_plan(self, config: ExecutiveProviderSyncConfig) -> dict:
        preflight = self.preflight(config)
        return {
            "connector": preflight.as_dict(),
            "provider_sync_config_id": str(config.id),
            "source": config.source,
            "sync_mode": config.sync_mode,
            "external_action_enabled": False,
            "requires_oauth": True,
            "oauth_configured": False,
            "will_contact_provider": False,
            "will_ingest_records": False,
            "will_send_email": False,
            "will_schedule_calendar": False,
            "planned_read_model": self.planned_read_model,
            "steps": [
                "Validate provider sync config remains READ_ONLY.",
                "Load OAuth credentials from an approved secret store when a real adapter is approved.",
                "Fetch provider records through a provider-specific read-only adapter.",
                "Normalize records into the existing read-only ingest API payload.",
                "Ingest normalized records through internal idempotent endpoints.",
            ],
        }


class OAuthReadOnlyConnector(DisabledReadOnlyConnector):
    adapter_available = True

    def preflight(self, config: ExecutiveProviderSyncConfig) -> ConnectorPreflight:
        preflight = super().preflight(config)
        blockers = list(preflight.blockers)
        warnings = list(preflight.warnings)
        oauth_reference = str(config.config.get("oauth_reference", "")).strip()
        if not oauth_reference:
            blockers.append("Approved OAuth secret reference is not configured.")
        return ConnectorPreflight(
            connector_key=preflight.connector_key,
            provider_name=preflight.provider_name,
            provider_type=preflight.provider_type,
            adapter_available=True,
            oauth_configured=bool(oauth_reference),
            external_action_enabled=False,
            dry_run_only=True,
            blockers=blockers,
            warnings=warnings,
        )

    def fetch_records(self, config: ExecutiveProviderSyncConfig, *, limit: int = 25) -> list[dict]:
        raise ReadOnlyConnectorAdapterError("OAuth-backed provider fetch is intentionally disabled until explicit approval.")


WRITE_SCOPE_MARKERS = ("send", "modify", "write", "smtp", "schedule", "readwrite")


class ApprovedReadOnlyConnector(DisabledReadOnlyConnector):
    adapter_available = True

    def preflight(self, config: ExecutiveProviderSyncConfig) -> ConnectorPreflight:
        preflight = DisabledReadOnlyConnector.preflight(self, config)
        reference_name = str(config.config.get("oauth_reference", "")).strip()
        warnings = list(preflight.warnings)
        oauth_configured = False
        if reference_name:
            from governance.models import SecretReference

            oauth_configured = SecretReference.objects.filter(
                name=reference_name,
                purpose=SecretReference.Purpose.OAUTH_READ_ONLY,
                provider=self.provider_name,
                active=True,
            ).exists()
            if not oauth_configured:
                warnings.append("OAuth secret reference is not an active read-only secret for this provider.")
        else:
            warnings.append("OAuth secret reference is not configured. Read-only fetch stays blocked until it is.")
        return ConnectorPreflight(
            connector_key=self.connector_key,
            provider_name=self.provider_name,
            provider_type=self.provider_type,
            adapter_available=True,
            oauth_configured=oauth_configured,
            external_action_enabled=False,
            dry_run_only=True,
            blockers=list(preflight.blockers),
            warnings=warnings,
        )

    def fetch_records(self, config: ExecutiveProviderSyncConfig, *, limit: int = 10) -> list[dict]:
        if config.sync_mode != ExecutiveProviderSyncConfig.SyncMode.READ_ONLY:
            raise ReadOnlyConnectorAdapterError("Provider fetch requires READ_ONLY sync mode.")
        if any(any(marker in str(scope).lower() for marker in WRITE_SCOPE_MARKERS) for scope in config.scopes):
            raise ReadOnlyConnectorAdapterError("Provider fetch refuses send, modify, write, or scheduling scopes.")
        from governance.secrets import SecretNotConfiguredError

        try:
            token = self._resolve_token(config)
        except SecretNotConfiguredError as exc:
            raise ReadOnlyConnectorAdapterError(str(exc)) from exc
        bounded_limit = max(1, min(int(limit), 25))
        return self._fetch_with_token(token, limit=bounded_limit)

    def _resolve_token(self, config: ExecutiveProviderSyncConfig) -> str:
        from governance.secrets import resolve_secret_value

        reference_name = str(config.config.get("oauth_reference", "")).strip()
        if not reference_name:
            raise ReadOnlyConnectorAdapterError("Approved OAuth secret reference is not configured.")
        return resolve_secret_value(name=reference_name, purpose="OAUTH_READ_ONLY", provider=self.provider_name)

    def _fetch_with_token(self, token: str, *, limit: int) -> list[dict]:
        raise ReadOnlyConnectorAdapterError("This connector has no read-only fetch implementation.")


class GmailReadOnlyConnector(ApprovedReadOnlyConnector):
    connector_key = "gmail_readonly"
    provider_name = "gmail"
    provider_type = ExecutiveProviderSyncConfig.ProviderType.EMAIL
    source_markers = ("gmail", "google_mail")
    required_scope_markers = ("gmail.readonly", "mail.readonly")
    planned_read_model = "email_messages"

    def _resolve_token(self, config: ExecutiveProviderSyncConfig) -> str:
        from executive_assistant.gmail_auth import gmail_access_token
        from governance.secrets import SecretNotConfiguredError

        try:
            return gmail_access_token(config)
        except SecretNotConfiguredError:
            return super()._resolve_token(config)

    def _fetch_with_token(self, token: str, *, limit: int) -> list[dict]:
        from executive_assistant.provider_http import http_json

        listing = http_json(
            "GET",
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages?maxResults={limit}",
            token=token,
        )
        records = []
        for item in listing.get("messages", [])[:limit]:
            message_id = str(item.get("id", "")).strip()
            if not message_id or "/" in message_id or not message_id.replace("-", "").replace("_", "").isalnum():
                continue
            detail = http_json(
                "GET",
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/"
                f"{message_id}?format=metadata&metadataHeaders=Subject&metadataHeaders=From",
                token=token,
            )
            headers = {
                str(header.get("name", "")).lower(): str(header.get("value", "")).strip()
                for header in detail.get("payload", {}).get("headers", [])
                if isinstance(header, dict)
            }
            sender = _email_address(headers.get("from", ""))
            if not sender:
                continue
            records.append(
                {
                    "source": "gmail_readonly",
                    "external_event_id": message_id,
                    "sender": sender,
                    "subject": headers.get("subject", "(no subject)") or "(no subject)",
                    "body": str(detail.get("snippet", "")).strip(),
                }
            )
        return records


class GoogleCalendarReadOnlyConnector(ApprovedReadOnlyConnector):
    connector_key = "google_calendar_readonly"
    provider_name = "google_calendar"
    provider_type = ExecutiveProviderSyncConfig.ProviderType.CALENDAR
    source_markers = ("google_calendar", "gcal", "calendar")
    required_scope_markers = ("calendar.readonly", "calendar.events.readonly")
    planned_read_model = "calendar_events"

    def _fetch_with_token(self, token: str, *, limit: int) -> list[dict]:
        from executive_assistant.provider_http import http_json

        listing = http_json(
            "GET",
            "https://www.googleapis.com/calendar/v3/calendars/primary/events"
            f"?maxResults={limit}&singleEvents=true&orderBy=startTime",
            token=token,
        )
        records = []
        for item in listing.get("items", [])[:limit]:
            if not isinstance(item, dict):
                continue
            event_id = str(item.get("id", "")).strip()
            start = item.get("start", {}) if isinstance(item.get("start"), dict) else {}
            end = item.get("end", {}) if isinstance(item.get("end"), dict) else {}
            starts_at = str(start.get("dateTime") or start.get("date") or "").strip()
            ends_at = str(end.get("dateTime") or end.get("date") or "").strip()
            if not event_id or not starts_at or not ends_at:
                continue
            organizer = item.get("organizer", {}) if isinstance(item.get("organizer"), dict) else {}
            records.append(
                {
                    "source": "google_calendar_readonly",
                    "external_event_id": event_id,
                    "title": str(item.get("summary", "(no title)")).strip() or "(no title)",
                    "starts_at": starts_at,
                    "ends_at": ends_at,
                    "organizer": str(organizer.get("email", "")).strip(),
                    "attendees": [],
                    "location": str(item.get("location", "")).strip(),
                    "description": str(item.get("description", "")).strip(),
                }
            )
        return records


class OutlookEmailReadOnlyConnector(ApprovedReadOnlyConnector):
    connector_key = "outlook_email_readonly"
    provider_name = "outlook_email"
    provider_type = ExecutiveProviderSyncConfig.ProviderType.EMAIL
    source_markers = ("outlook", "microsoft_mail", "office365_mail")
    required_scope_markers = ("mail.read", "mail.readbasic")
    planned_read_model = "email_messages"

    def _fetch_with_token(self, token: str, *, limit: int) -> list[dict]:
        from executive_assistant.provider_http import http_json

        listing = http_json(
            "GET",
            "https://graph.microsoft.com/v1.0/me/messages"
            f"?$select=id,subject,from,bodyPreview&$top={limit}",
            token=token,
        )
        records = []
        for item in listing.get("value", [])[:limit]:
            if not isinstance(item, dict):
                continue
            message_id = str(item.get("id", "")).strip()
            if not message_id:
                continue
            sender = ""
            from_field = item.get("from", {})
            if isinstance(from_field, dict):
                address = from_field.get("emailAddress", {})
                if isinstance(address, dict):
                    sender = str(address.get("address", "")).strip()
            records.append(
                {
                    "source": "outlook_email_readonly",
                    "external_event_id": message_id,
                    "sender": sender or "unknown",
                    "subject": str(item.get("subject", "(no subject)")).strip() or "(no subject)",
                    "body": str(item.get("bodyPreview", "")).strip(),
                }
            )
        return records


class OutlookCalendarReadOnlyConnector(ApprovedReadOnlyConnector):
    connector_key = "outlook_calendar_readonly"
    provider_name = "outlook_calendar"
    provider_type = ExecutiveProviderSyncConfig.ProviderType.CALENDAR
    source_markers = ("outlook_calendar", "microsoft_calendar", "office365_calendar")
    required_scope_markers = ("calendars.read",)
    planned_read_model = "calendar_events"

    def _fetch_with_token(self, token: str, *, limit: int) -> list[dict]:
        from executive_assistant.provider_http import http_json

        listing = http_json(
            "GET",
            "https://graph.microsoft.com/v1.0/me/events"
            f"?$select=id,subject,start,end,organizer,location&$top={limit}",
            token=token,
        )
        records = []
        for item in listing.get("value", [])[:limit]:
            if not isinstance(item, dict):
                continue
            event_id = str(item.get("id", "")).strip()
            start = item.get("start", {}) if isinstance(item.get("start"), dict) else {}
            end = item.get("end", {}) if isinstance(item.get("end"), dict) else {}
            starts_at = str(start.get("dateTime", "")).strip()
            ends_at = str(end.get("dateTime", "")).strip()
            if not event_id or not starts_at or not ends_at:
                continue
            organizer = item.get("organizer", {}) if isinstance(item.get("organizer"), dict) else {}
            address = organizer.get("emailAddress", {}) if isinstance(organizer.get("emailAddress"), dict) else {}
            location = item.get("location", {}) if isinstance(item.get("location"), dict) else {}
            records.append(
                {
                    "source": "outlook_calendar_readonly",
                    "external_event_id": event_id,
                    "title": str(item.get("subject", "(no title)")).strip() or "(no title)",
                    "starts_at": starts_at,
                    "ends_at": ends_at,
                    "organizer": str(address.get("address", "")).strip(),
                    "attendees": [],
                    "location": str(location.get("displayName", "")).strip(),
                    "description": "",
                }
            )
        return records


CONNECTORS: tuple[ApprovedReadOnlyConnector, ...] = (
    GmailReadOnlyConnector(),
    GoogleCalendarReadOnlyConnector(),
    OutlookEmailReadOnlyConnector(),
    OutlookCalendarReadOnlyConnector(),
)


def list_read_only_connectors() -> list[dict]:
    return [
        {
            "connector_key": connector.connector_key,
            "provider_name": connector.provider_name,
            "provider_type": connector.provider_type,
            "adapter_available": connector.adapter_available,
            "oauth_configured": connector.oauth_configured,
            "external_action_enabled": False,
            "dry_run_only": True,
            "read_only_fetch_approved": True,
        }
        for connector in CONNECTORS
    ]


def get_read_only_connector(config: ExecutiveProviderSyncConfig) -> DisabledReadOnlyConnector:
    for connector in CONNECTORS:
        if connector.matches(config):
            return connector
    return DisabledReadOnlyConnector()
