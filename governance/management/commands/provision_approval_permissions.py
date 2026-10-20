from django.core.management.base import BaseCommand

from governance.services import provision_approval_groups


class Command(BaseCommand):
    help = "Provision approval dashboard groups and permissions."

    def handle(self, *args, **options):
        groups = provision_approval_groups()
        for group_name, permissions in groups.items():
            self.stdout.write(f"{group_name}: {', '.join(permissions)}")
        self.stdout.write(self.style.SUCCESS("Provisioned approval permission groups."))
