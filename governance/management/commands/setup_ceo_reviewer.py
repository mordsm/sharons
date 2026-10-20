from django.core.management.base import BaseCommand, CommandError

from governance.services import APPROVAL_DECIDER_GROUP, setup_ceo_reviewer


class Command(BaseCommand):
    help = "Create or update the initial CEO reviewer account and assign approval decision permissions."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--email", default="")
        parser.add_argument("--password", default="")

    def handle(self, *args, **options):
        try:
            user, created = setup_ceo_reviewer(
                username=options["username"],
                email=options["email"],
                password=options["password"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        status = "Created" if created else "Updated"
        password_status = "password set" if options["password"] else "unusable password"
        self.stdout.write(
            self.style.SUCCESS(
                f"{status} reviewer '{user.get_username()}' with {password_status}; assigned {APPROVAL_DECIDER_GROUP}."
            )
        )
