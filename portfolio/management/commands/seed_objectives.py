from django.core.management.base import BaseCommand

from portfolio.services import seed_approved_objectives


class Command(BaseCommand):
    help = "Seed the approved 90-day Sharons objectives."

    def add_arguments(self, parser):
        parser.add_argument("--correlation-id", default="seed-objectives")
        parser.add_argument("--actor-id", default="system")

    def handle(self, *args, **options):
        strategy, objectives = seed_approved_objectives(
            actor_id=options["actor_id"],
            correlation_id=options["correlation_id"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded strategy version {strategy.version} with {len(objectives)} active objectives."
            )
        )
