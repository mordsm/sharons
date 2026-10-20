from dataclasses import dataclass

from executive_assistant.models import ExecutiveProviderSyncConfig


class ReadOnlyConnectorAdapterError(Exception):
    """Raised when a provider adapter would need unavailable external access."""


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


class GmailReadOnlyConnector(DisabledReadOnlyConnector):
    connector_key = "gmail_readonly"
    provider_name = "gmail"
    provider_type = ExecutiveProviderSyncConfig.ProviderType.EMAIL
    source_markers = ("gmail", "google_mail")
    required_scope_markers = ("gmail.readonly", "mail.readonly")
    planned_read_model = "email_messages"


class GoogleCalendarReadOnlyConnector(DisabledReadOnlyConnector):
    connector_key = "google_calendar_readonly"
    provider_name = "google_calendar"
    provider_type = ExecutiveProviderSyncConfig.ProviderType.CALENDAR
    source_markers = ("google_calendar", "gcal", "calendar")
    required_scope_markers = ("calendar.readonly", "calendar.events.readonly")
    planned_read_model = "calendar_events"


class OutlookEmailReadOnlyConnector(DisabledReadOnlyConnector):
    connector_key = "outlook_email_readonly"
    provider_name = "outlook_email"
    provider_type = ExecutiveProviderSyncConfig.ProviderType.EMAIL
    source_markers = ("outlook", "microsoft_mail", "office365_mail")
    required_scope_markers = ("mail.read", "mail.readbasic")
    planned_read_model = "email_messages"


class OutlookCalendarReadOnlyConnector(DisabledReadOnlyConnector):
    connector_key = "outlook_calendar_readonly"
    provider_name = "outlook_calendar"
    provider_type = ExecutiveProviderSyncConfig.ProviderType.CALENDAR
    source_markers = ("outlook_calendar", "microsoft_calendar", "office365_calendar")
    required_scope_markers = ("calendars.read",)
    planned_read_model = "calendar_events"


CONNECTORS: tuple[DisabledReadOnlyConnector, ...] = (
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
        }
        for connector in CONNECTORS
    ]


def get_read_only_connector(config: ExecutiveProviderSyncConfig) -> DisabledReadOnlyConnector:
    for connector in CONNECTORS:
        if connector.matches(config):
            return connector
    return DisabledReadOnlyConnector()
