from django.core.management.base import BaseCommand

from apps.analytics.services import seed_builtin_report_definitions
from apps.circulation.models import CirculationPolicy
from apps.holdings.models import Branch, Location
from apps.notifications.services import seed_default_templates
from apps.vocabularies.models import ClassificationScheme, ControlledVocabulary


class Command(BaseCommand):
    help = "Seed baseline library configuration for local development."

    def handle(self, *args, **options):
        branch, _ = Branch.objects.get_or_create(
            code="main",
            defaults={"name": "總館", "timezone": "Asia/Taipei"},
        )
        Location.objects.get_or_create(
            branch=branch,
            code="stack",
            defaults={"name": "一般書庫", "shelving_area": "開架書區"},
        )
        Location.objects.get_or_create(
            branch=branch,
            code="ref",
            defaults={"name": "參考書區", "shelving_area": "館內閱覽"},
        )

        vocabularies = [
            (
                "lcsh",
                "Library of Congress Subject Headings",
                "https://id.loc.gov/authorities/subjects.html",
                False,
            ),
            ("fast", "Faceted Application of Subject Terminology", "https://fast.oclc.org/", False),
            ("local-subjects", "本地主題詞表", "", True),
        ]
        for code, name, uri, is_local in vocabularies:
            ControlledVocabulary.objects.get_or_create(
                code=code,
                defaults={"name": name, "source_uri": uri, "is_local": is_local},
            )

        schemes = [
            (
                "lcc",
                "Library of Congress Classification",
                "",
                "https://www.loc.gov/catdir/cpso/lcco/",
            ),
            ("ddc", "Dewey Decimal Classification", "", "https://www.oclc.org/dewey/"),
            ("clc-tw", "中文圖書分類法", "local", ""),
        ]
        for code, name, edition, uri in schemes:
            ClassificationScheme.objects.get_or_create(
                code=code,
                defaults={"name": name, "edition": edition, "source_uri": uri},
            )

        CirculationPolicy.objects.get_or_create(
            name="Default circulation policy",
            defaults={
                "priority": 9999,
                "loan_period_days": 14,
                "renewal_period_days": 14,
                "max_renewals": 2,
                "max_open_loans": 20,
                "max_holds": 10,
                "allow_holds": True,
                "allow_renewal_when_holds": False,
                "hold_shelf_days": 7,
                "overdue_grace_days": 0,
                "overdue_fee_per_day": 5,
                "max_overdue_fee": 500,
                "fee_block_threshold": 1000,
                "is_active": True,
            },
        )

        seed_builtin_report_definitions()

        seed_default_templates()

        self.stdout.write(self.style.SUCCESS("Seeded LibraCore baseline data."))
