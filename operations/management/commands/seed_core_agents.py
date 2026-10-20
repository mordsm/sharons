from django.core.management.base import BaseCommand

from operations.services import seed_core_agents


class Command(BaseCommand):
    help = "Seed the approved core company agents."

    def add_arguments(self, parser):
        parser.add_argument("--correlation-id", default="seed-core-agents")
        parser.add_argument("--actor-id", default="chief_of_staff")

    def handle(self, *args, **options):
        agents = seed_core_agents(
            actor_id=options["actor_id"],
            correlation_id=options["correlation_id"],
        )
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(agents)} core agents."))
