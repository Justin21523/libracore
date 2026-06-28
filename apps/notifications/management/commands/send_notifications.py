from django.core.management.base import BaseCommand

from apps.notifications.services import send_pending_notifications


class Command(BaseCommand):
    help = "Send pending email notifications."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=None)

    def handle(self, *args, **options):
        result = send_pending_notifications(limit=options["limit"])
        self.stdout.write(self.style.SUCCESS(f"Sent notifications: {result}"))
