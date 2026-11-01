from django.core.management.base import BaseCommand

from executive_assistant.models import ExecutiveProviderSyncConfig
from governance.models import SecretReference


REFERENCES = (
    {
        "name": "gmail-access",
        "purpose": SecretReference.Purpose.OAUTH_READ_ONLY,
        "provider": "gmail",
        "env_var_name": "SHARONS_GMAIL_TOKEN",
    },
    {
        "name": "gmail-refresh",
        "purpose": SecretReference.Purpose.OAUTH_REFRESH,
        "provider": "gmail",
        "env_var_name": "SHARONS_GMAIL_REFRESH_TOKEN",
    },
    {
        "name": "github-issues",
        "purpose": SecretReference.Purpose.GITHUB_ISSUE_CREATE,
        "provider": "github",
        "env_var_name": "SHARONS_GITHUB_TOKEN",
    },
)


class Command(BaseCommand):
    help = "Register approved connector secret references. Values stay in the environment."

    def handle(self, *args, **options):
        for item in REFERENCES:
            SecretReference.objects.update_or_create(
                name=item["name"],
                defaults={**item, "active": True, "created_by": "register_connector_secrets"},
            )
            self.stdout.write(f"registered {item['name']} -> {item['env_var_name']}")

        config, created = ExecutiveProviderSyncConfig.objects.get_or_create(
            provider_type=ExecutiveProviderSyncConfig.ProviderType.EMAIL,
            provider_name="gmail",
            source="gmail_readonly",
            defaults={
                "sync_mode": ExecutiveProviderSyncConfig.SyncMode.READ_ONLY,
                "status": ExecutiveProviderSyncConfig.Status.READY_FOR_CONNECTOR,
                "scopes": ["gmail.readonly"],
                "config": {"oauth_reference": "gmail-access", "oauth_refresh_reference": "gmail-refresh"},
                "no_external_action": True,
                "created_by": "register_connector_secrets",
            },
        )
        if not created:
            config.scopes = ["gmail.readonly"]
            config.config = {"oauth_reference": "gmail-access", "oauth_refresh_reference": "gmail-refresh"}
            config.status = ExecutiveProviderSyncConfig.Status.READY_FOR_CONNECTOR
            config.no_external_action = True
            config.save(update_fields=["scopes", "config", "status", "no_external_action"])
        self.stdout.write("gmail sync config points at gmail-access and gmail-refresh")
