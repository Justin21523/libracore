from django.core.management.base import BaseCommand

from apps.discovery.indexing import rebuild_all_indexes


class Command(BaseCommand):
    help = "Rebuild public OPAC/discovery SearchDocument records."

    def handle(self, *args, **options):
        stats = rebuild_all_indexes()
        self.stdout.write(
            self.style.SUCCESS(
                f"Rebuilt discovery index: indexed={stats.indexed}, removed={stats.removed}"
            )
        )

