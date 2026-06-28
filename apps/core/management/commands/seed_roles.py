from django.core.management.base import BaseCommand

from apps.core.roles import ROLE_LABELS, seed_role_groups


class Command(BaseCommand):
    help = "Create LibraCore staff role groups."

    def handle(self, *args, **options):
        groups = seed_role_groups()
        for group in groups:
            self.stdout.write(f"{group.name}: {ROLE_LABELS[group.name]}")
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(groups)} role groups."))
