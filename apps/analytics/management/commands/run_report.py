from django.core.management.base import BaseCommand, CommandError

from apps.analytics.services import ReportPermissionError, UnknownReportError, run_report


class Command(BaseCommand):
    help = "Run a built-in LibraCore analytics report synchronously."

    def add_arguments(self, parser):
        parser.add_argument("--code", required=True)
        parser.add_argument("--date-from")
        parser.add_argument("--date-to")
        parser.add_argument("--days", type=int)
        parser.add_argument("--limit", type=int)

    def handle(self, *args, **options):
        parameters = {
            key: value
            for key, value in {
                "date_from": options.get("date_from"),
                "date_to": options.get("date_to"),
                "days": options.get("days"),
                "limit": options.get("limit"),
            }.items()
            if value not in (None, "")
        }
        try:
            report_run = run_report(options["code"], parameters=parameters)
        except (ReportPermissionError, UnknownReportError) as exc:
            raise CommandError(str(exc)) from exc

        if report_run.status == report_run.Status.FAILED:
            raise CommandError(report_run.error_report)
        self.stdout.write(
            self.style.SUCCESS(
                f"Completed {report_run.code}: {report_run.record_count} rows, "
                f"csv={report_run.csv_file.name}"
            )
        )
        self.stdout.write(str(report_run.result_json.get("summary", {})))
