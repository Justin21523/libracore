from django.core.management.base import BaseCommand

from apps.notifications.services import generate_notifications


class Command(BaseCommand):
    help = "Generate reader and staff notifications."

    def add_arguments(self, parser):
        parser.add_argument("--type", dest="notification_type", default=None)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        result = generate_notifications(
            notification_type=options["notification_type"],
            dry_run=options["dry_run"],
        )
        self.stdout.write(self.style.SUCCESS(f"Generated notifications: {result}"))
