from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Print a local backup manifest. Remote backup is intentionally not implemented."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", default=True)

    def handle(self, *args, **options):
        database = settings.DATABASES["default"]
        manifest = {
            "database_engine": database["ENGINE"],
            "database_name": str(database.get("NAME", "")),
            "media_root": str(settings.MEDIA_ROOT),
            "static_root": str(settings.STATIC_ROOT),
            "exports_dir": str(Path(settings.MEDIA_ROOT) / "exports"),
            "remote_backup": "not_configured",
        }
        for key, value in manifest.items():
            self.stdout.write(f"{key}: {value}")
        self.stdout.write(self.style.WARNING("Dry-run only: no backup archive was created."))
