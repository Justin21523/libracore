from django.core.management.base import BaseCommand

from apps.core.retention import apply_retention_policy


class Command(BaseCommand):
    help = "Apply or preview LibraCore privacy and retention policy."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--loan-days", type=int, default=365)
        parser.add_argument("--notification-days", type=int, default=180)
        parser.add_argument("--audit-years", type=int, default=7)

    def handle(self, *args, **options):
        result = apply_retention_policy(
            apply=options["apply"],
            loan_days=options["loan_days"],
            notification_days=options["notification_days"],
            audit_years=options["audit_years"],
        )
        mode = "APPLY" if options["apply"] else "DRY-RUN"
        self.stdout.write(f"mode: {mode}")
        self.stdout.write(f"loans_anonymized: {result.loans_anonymized}")
        self.stdout.write(f"notifications_deleted: {result.notifications_deleted}")
        self.stdout.write(f"audit_logs_deleted: {result.audit_logs_deleted}")
