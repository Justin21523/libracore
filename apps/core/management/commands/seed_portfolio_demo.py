from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.acquisitions.models import (
    AcquisitionOrder,
    AcquisitionOrderLine,
    Fund,
    Invoice,
    InvoiceLine,
    PurchaseRequest,
    Vendor,
)
from apps.analytics.models import ReportDefinition, ReportRun
from apps.authorities.models import AccessPoint, AuthorityRecord, AuthorityRelation, ExternalIdentifier
from apps.catalog.models import BibliographicRecord, Instance, InstanceContributor, Work, WorkAuthorityLink
from apps.circulation.models import CirculationPolicy, FineFee, HoldRequest, Loan, Patron, Payment
from apps.core.data_quality import run_data_quality_checks
from apps.core.models import AuditLog
from apps.discovery.indexing import rebuild_all_indexes
from apps.erm.models import (
    AccessUrl,
    Coverage,
    ElectronicResource,
    License,
    LicenseTerm,
    Package,
    Platform,
    ProxyConfig,
)
from apps.holdings.models import Branch, Holding, Item, Location
from apps.marc.models import AuthorityLinkSuggestion, MarcImportBatch, MarcImportRecord, MarcMatchCandidate, MarcRecord
from apps.repository.models import DigitalObject, FileAsset
from apps.serials.models import BoundVolume, Issue, IssuePredictionPattern, SerialTitle, Subscription


class Command(BaseCommand):
    help = "Seed a rich, screenshot-friendly LibraCore portfolio demo dataset."

    def handle(self, *args, **options):
        call_command("seed_libracore", verbosity=0)
        now = timezone.now()
        today = timezone.localdate()
        User = get_user_model()

        staff, _ = User.objects.get_or_create(
            username="demo_staff",
            defaults={"email": "demo_staff@libracore.local", "is_staff": True, "is_superuser": True},
        )
        staff.is_staff = True
        staff.is_superuser = True
        staff.set_password("demo_staff_pass")
        staff.save()

        reader_user, _ = User.objects.get_or_create(
            username="demo_reader",
            defaults={"email": "demo_reader@libracore.local", "first_name": "Demo", "last_name": "Reader"},
        )
        reader_user.set_password("demo_reader_pass")
        reader_user.save()

        branch, _ = Branch.objects.update_or_create(
            code="demo-main",
            defaults={"name": "LibraCore 總館", "address": "臺北市知識路 1 號", "timezone": "Asia/Taipei"},
        )
        stack, _ = Location.objects.update_or_create(
            branch=branch,
            code="open-stack",
            defaults={"name": "開架書庫", "shelving_area": "3F 知識組織區", "is_public": True},
        )
        eres, _ = Location.objects.update_or_create(
            branch=branch,
            code="e-resource",
            defaults={"name": "電子資源", "shelving_area": "線上館藏", "is_public": True},
        )
        serial_loc, _ = Location.objects.update_or_create(
            branch=branch,
            code="serials",
            defaults={"name": "期刊區", "shelving_area": "2F 期刊閱覽區", "is_public": True},
        )

        CirculationPolicy.objects.update_or_create(
            name="Demo standard circulation policy",
            defaults={
                "priority": 10,
                "patron_type": "standard",
                "branch": branch,
                "loan_period_days": 21,
                "renewal_period_days": 14,
                "max_renewals": 2,
                "max_open_loans": 20,
                "max_holds": 10,
                "allow_holds": True,
                "overdue_fee_per_day": 5,
                "max_overdue_fee": 500,
                "fee_block_threshold": 1000,
                "is_active": True,
            },
        )

        cataloger = self._authority(
            AuthorityRecord.AuthorityType.PERSON,
            "王大明",
            source="lcnaf",
            control_number="n-demo-0001",
            uri="https://viaf.org/viaf/123456789",
            variants=["Wang, Daming", "王, 大明"],
        )
        subject = self._authority(
            AuthorityRecord.AuthorityType.SUBJECT,
            "知識組織",
            source="lcsh-local",
            control_number="sh-demo-0001",
            uri="https://id.loc.gov/authorities/subjects/sh85076807",
            variants=["Knowledge organization", "資訊組織"],
        )
        place = self._authority(
            AuthorityRecord.AuthorityType.PLACE,
            "臺灣",
            source="naf-local",
            control_number="n-demo-geo-1",
            uri="https://id.loc.gov/authorities/names/n79053795",
            variants=["Taiwan", "台灣"],
        )
        AuthorityRelation.objects.get_or_create(
            source=subject,
            target=place,
            relation_type=AuthorityRelation.RelationType.RELATED,
            defaults={"note": "Demo relation for subject browse."},
        )

        work, _ = Work.objects.update_or_create(
            primary_title="圖書資訊學導論",
            defaults={
                "language_hint": "chi",
                "form": "text",
                "date": "2026",
                "summary": "展示 RDA、MARC21、權威控制、Discovery 與館藏管理的樣本作品。",
            },
        )
        WorkAuthorityLink.objects.get_or_create(
            work=work,
            authority=cataloger,
            role=WorkAuthorityLink.Role.CREATOR,
            defaults={"relationship_designator": "author"},
        )
        WorkAuthorityLink.objects.get_or_create(
            work=work,
            authority=subject,
            role=WorkAuthorityLink.Role.SUBJECT,
            defaults={"relationship_designator": "topic"},
        )
        instance, _ = Instance.objects.update_or_create(
            title_statement="圖書資訊學導論 : RDA、MARC21 與 Discovery 實務",
            defaults={
                "work": work,
                "resource_type": Instance.ResourceType.BOOK,
                "variant_titles": ["Introduction to Library and Information Science"],
                "responsibility_statement": "王大明著",
                "edition_statement": "初版",
                "publication_place": "臺北市",
                "publisher": "LibraCore Press",
                "publication_date": "2026",
                "extent": "320 pages",
                "content_type": "text",
                "media_type": "unmediated",
                "carrier_type": "volume",
                "identifiers": [{"scheme": "ISBN", "value": "9789860000001"}],
                "notes": [{"type": "summary", "value": "含權威控制、控制詞彙、OPAC faceting 與 ERM 範例。"}],
            },
        )
        InstanceContributor.objects.get_or_create(instance=instance, authority=cataloger, role="creator", marc_tag="100")
        bib, _ = BibliographicRecord.objects.update_or_create(
            source="demo",
            control_number="LC-DEMO-0001",
            defaults={
                "status": BibliographicRecord.Status.APPROVED,
                "encoding_level": " ",
                "work": work,
                "instance": instance,
                "metadata": {
                    "subjects": [{"label": "知識組織"}, {"label": "圖書館自動化"}],
                    "marc_control_fields": {"001": "LC-DEMO-0001", "008": "260101s2026    ch a     b    000 0 chi d"},
                },
            },
        )
        MarcRecord.objects.update_or_create(
            bibliographic_record=bib,
            format_type=MarcRecord.FormatType.BIBLIOGRAPHIC,
            control_number="LC-DEMO-0001",
            defaults={
                "source": "demo",
                "leader": "01247nam a2200301 i 4500",
                "validation_status": MarcRecord.ValidationStatus.VALID,
                "parsed_json": {
                    "leader": "01247nam a2200301 i 4500",
                    "fields": [
                        {"001": "LC-DEMO-0001"},
                        {"020": {"subfields": [{"a": "9789860000001"}]}},
                        {"245": {"ind1": "1", "ind2": "0", "subfields": [{"a": "圖書資訊學導論 :"}, {"b": "RDA、MARC21 與 Discovery 實務 /"}, {"c": "王大明著"}]}},
                    ],
                },
                "marcxml": "<record><controlfield tag=\"001\">LC-DEMO-0001</controlfield></record>",
                "imported_at": now,
            },
        )
        holding, _ = Holding.objects.update_or_create(
            instance=instance,
            branch=branch,
            location=stack,
            defaults={"textual_holdings": "LibraCore 總館：開架書庫 1 冊可借", "public_note": "Demo shelving: Z665 .W36 2026"},
        )
        item1, _ = Item.objects.update_or_create(
            barcode="LC-DEMO-I001",
            defaults={"holding": holding, "copy_number": "c.1", "status": Item.Status.AVAILABLE, "price": Decimal("680.00"), "acquired_at": today},
        )
        item2, _ = Item.objects.update_or_create(
            barcode="LC-DEMO-I002",
            defaults={"holding": holding, "copy_number": "c.2", "status": Item.Status.ON_LOAN, "price": Decimal("680.00"), "acquired_at": today},
        )

        patron, _ = Patron.objects.update_or_create(
            user=reader_user,
            defaults={"barcode": "LC-P0001", "patron_type": "standard", "home_branch": branch, "expiry_date": today + timedelta(days=365), "privacy_opt_in": True},
        )
        loan, _ = Loan.objects.update_or_create(
            item=item2,
            patron=patron,
            status=Loan.Status.OPEN,
            defaults={"due_at": now + timedelta(days=10), "renew_count": 1},
        )
        HoldRequest.objects.update_or_create(
            patron=patron,
            instance=instance,
            item=item1,
            defaults={"pickup_location": stack, "status": HoldRequest.Status.READY, "queue_position": 1, "expires_at": now + timedelta(days=5)},
        )
        FineFee.objects.update_or_create(
            patron=patron,
            reason="Demo overdue balance",
            defaults={"loan": loan, "fee_type": FineFee.FeeType.OVERDUE, "amount": Decimal("25.00"), "original_amount": Decimal("25.00"), "balance_amount": Decimal("25.00"), "assessed_at": now},
        )
        Payment.objects.get_or_create(
            patron=patron,
            reference="DEMO-PAY-001",
            defaults={"amount": Decimal("50.00"), "method": Payment.Method.CASH, "received_by": staff, "note": "Demo partial payment"},
        )

        vendor, _ = Vendor.objects.update_or_create(
            code="demo-bookco",
            defaults={"name": "BookCo Demo Vendor", "contact": {"email": "orders@example.invalid"}},
        )
        fund, _ = Fund.objects.update_or_create(
            code="demo-monographs",
            defaults={"name": "Demo Monographs Fund", "fiscal_year": "2026", "allocated_amount": Decimal("150000.00")},
        )
        pr, _ = PurchaseRequest.objects.update_or_create(
            title="資料治理與圖書館系統設計",
            defaults={"requester": staff, "vendor": vendor, "status": PurchaseRequest.Status.APPROVED, "isbn": "9789860000002", "publisher": "LibraCore Press", "publication_date": "2026", "estimated_price": Decimal("720.00"), "quantity": 2},
        )
        order, _ = AcquisitionOrder.objects.update_or_create(
            order_number="PO-DEMO-2026-001",
            defaults={"vendor": vendor, "purchase_request": pr, "status": AcquisitionOrder.Status.PARTIALLY_RECEIVED, "ordered_at": today, "notes": "Demo order linked to receiving workflow."},
        )
        line, _ = AcquisitionOrderLine.objects.update_or_create(
            order=order,
            title="資料治理與圖書館系統設計",
            defaults={"isbn": "9789860000002", "publisher": "LibraCore Press", "publication_date": "2026", "branch": branch, "location": stack, "fund": fund, "quantity": 2, "unit_price": Decimal("720.00"), "received_quantity": 1, "receiving_status": AcquisitionOrderLine.ReceivingStatus.PARTIALLY_RECEIVED},
        )
        invoice, _ = Invoice.objects.update_or_create(
            vendor=vendor,
            invoice_number="INV-DEMO-001",
            defaults={"order": order, "issued_at": today, "total_amount": Decimal("720.00"), "match_status": "review"},
        )
        InvoiceLine.objects.update_or_create(
            invoice=invoice,
            order_line=line,
            defaults={"quantity": 1, "unit_price": Decimal("720.00"), "line_total": Decimal("720.00"), "match_status": InvoiceLine.MatchStatus.REVIEW},
        )

        serial_instance, _ = Instance.objects.update_or_create(
            title_statement="Journal of Knowledge Organization",
            defaults={"work": work, "resource_type": Instance.ResourceType.SERIAL, "publisher": "Demo Society", "publication_date": "2026-", "identifiers": [{"scheme": "ISSN", "value": "3000-0001"}]},
        )
        serial_holding, _ = Holding.objects.update_or_create(
            instance=serial_instance,
            branch=branch,
            location=serial_loc,
            defaults={"textual_holdings": "v.12:no.1(2026)- 最新期刊區"},
        )
        serial, _ = SerialTitle.objects.update_or_create(
            title="Journal of Knowledge Organization",
            defaults={"instance": serial_instance, "issn": "3000-0001", "frequency": "monthly", "holding": serial_holding, "current_volume": 12, "current_number": 3},
        )
        sub, _ = Subscription.objects.update_or_create(
            serial_title=serial,
            vendor=vendor,
            branch=branch,
            location=serial_loc,
            defaults={"start_date": today.replace(month=1, day=1), "status": Subscription.Status.ACTIVE, "create_item_on_checkin": True},
        )
        IssuePredictionPattern.objects.update_or_create(
            subscription=sub,
            defaults={"frequency": IssuePredictionPattern.Frequency.MONTHLY, "enumeration_captions": ["v.", "no."], "next_expected_at": today + timedelta(days=30), "next_volume": 12, "next_number": 4},
        )
        issue1, _ = Issue.objects.update_or_create(
            serial_title=serial,
            enumeration="v.12:no.1",
            chronology="2026-01",
            defaults={"subscription": sub, "expected_at": today - timedelta(days=45), "received_at": today - timedelta(days=43), "status": Issue.Status.RECEIVED, "holding": serial_holding},
        )
        Issue.objects.update_or_create(
            serial_title=serial,
            enumeration="v.12:no.2",
            chronology="2026-02",
            defaults={"subscription": sub, "expected_at": today - timedelta(days=15), "status": Issue.Status.MISSING, "holding": serial_holding, "claim_count": 1},
        )
        BoundVolume.objects.update_or_create(
            serial_title=serial,
            label="Journal of Knowledge Organization v.11 (2025)",
            defaults={"holding": serial_holding, "bound_at": today - timedelta(days=60)},
        )

        license_obj, _ = License.objects.update_or_create(
            name="Knowledge Online License 2026",
            defaults={"licensor": "Knowledge Online", "vendor": vendor, "invoice": invoice, "status": License.Status.ACTIVE, "starts_at": today.replace(month=1, day=1), "ends_at": today + timedelta(days=180), "renewal_notice_days": 60, "terms": {"remote_access": True, "walk_in_users": True, "ill": "limited"}},
        )
        for term_type, allowed, limit in [
            (LicenseTerm.TermType.WALK_IN_USERS, True, ""),
            (LicenseTerm.TermType.REMOTE_ACCESS, True, "Proxy users"),
            (LicenseTerm.TermType.INTERLIBRARY_LOAN, False, "No e-copy delivery"),
            (LicenseTerm.TermType.CONCURRENT_USERS, True, "50"),
        ]:
            LicenseTerm.objects.update_or_create(license=license_obj, term_type=term_type, defaults={"allowed": allowed, "limit_value": limit})
        platform, _ = Platform.objects.update_or_create(
            code="knowledge-online",
            defaults={"name": "Knowledge Online Platform", "vendor": vendor, "base_url": "https://example.invalid/knowledge"},
        )
        package, _ = Package.objects.update_or_create(
            name="Knowledge Organization Complete",
            defaults={"platform": platform, "vendor": vendor, "license": license_obj, "status": Package.Status.ACTIVE, "starts_at": today.replace(month=1, day=1), "ends_at": today + timedelta(days=180)},
        )
        proxy, _ = ProxyConfig.objects.update_or_create(
            code="ezproxy-demo",
            defaults={"name": "Demo EZproxy", "proxy_prefix": "https://proxy.example.invalid/login?url=", "is_default": True, "is_active": True},
        )
        resource, _ = ElectronicResource.objects.update_or_create(
            title="Knowledge Organization Online",
            defaults={"instance": serial_instance, "resource_kind": ElectronicResource.ResourceKind.DATABASE, "status": ElectronicResource.Status.ACTIVE, "resource_mode": ElectronicResource.ResourceMode.ONLINE, "platform": platform.name, "platform_ref": platform, "package": package, "access_url": "https://example.invalid/knowledge", "license": license_obj, "authentication_method": "IP + proxy", "identifiers": [{"scheme": "DBID", "value": "KO-DEMO"}], "is_public": True},
        )
        Coverage.objects.update_or_create(resource=resource, coverage_type=Coverage.CoverageType.FULL_TEXT, defaults={"start_date": today.replace(year=2010, month=1, day=1), "coverage_note": "Available from 2010-01-01 to present"})
        AccessUrl.objects.update_or_create(resource=resource, label="Full text access", defaults={"url": "https://example.invalid/knowledge", "is_primary": True, "requires_proxy": True, "proxy_config": proxy})

        digital, _ = DigitalObject.objects.update_or_create(
            title="LibraCore Demo Dublin Core Record",
            defaults={"bibliographic_record": bib, "status": DigitalObject.Status.PUBLISHED, "oai_identifier": "oai:libracore.demo:0001", "rights_statement": "Open demo record.", "dc_metadata": {"title": "LibraCore Demo Dublin Core Record", "creator": "王大明", "subject": ["知識組織", "數位典藏"], "description": "A sample object for repository and OAI-PMH demonstration."}},
        )
        FileAsset.objects.update_or_create(
            digital_object=digital,
            label="OCR full text sample",
            defaults={"file": "repository/demo-fulltext.txt", "mime_type": "text/plain", "size_bytes": 2048, "checksum_sha256": "0" * 64, "ocr_text": "LibraCore repository demo full text for search and OAI-PMH.", "access_level": "public"},
        )

        batch, _ = MarcImportBatch.objects.update_or_create(
            filename="demo-marc-batch.mrc",
            defaults={"source": "portfolio-demo", "import_format": MarcImportBatch.ImportFormat.JSON, "status": MarcImportBatch.Status.PARSED, "submitted_by": staff, "started_at": now - timedelta(hours=2), "completed_at": now - timedelta(hours=1), "record_count": 3, "valid_count": 2, "invalid_count": 1, "conflict_count": 1, "notes": "Portfolio demo import batch."},
        )
        record, _ = MarcImportRecord.objects.update_or_create(
            batch=batch,
            sequence=1,
            defaults={"format_type": "bibliographic", "raw_payload": "{\"leader\":\"01247nam a2200301 i 4500\"}", "parsed_json": {"leader": "01247nam a2200301 i 4500", "fields": [{"001": "LC-DEMO-0001"}, {"245": "圖書資訊學導論"}]}, "mapped_json": {"work": {"primary_title": "圖書資訊學導論"}, "instance": {"title_statement": instance.title_statement}}, "status": MarcImportRecord.Status.CONFLICT, "control_number": "LC-DEMO-0001", "conflict_reason": "Existing ISBN candidate found.", "bibliographic_record": bib},
        )
        MarcMatchCandidate.objects.update_or_create(
            import_record=record,
            target_type=MarcMatchCandidate.TargetType.INSTANCE,
            target_id=str(instance.id),
            match_rule="isbn_exact",
            defaults={"confidence": 98, "reason": "ISBN 9789860000001 already exists.", "payload": {"title": instance.title_statement}, "selected": True},
        )
        AuthorityLinkSuggestion.objects.update_or_create(
            import_record=record,
            marc_tag="650",
            label="知識組織",
            defaults={"authority_type": AuthorityRecord.AuthorityType.SUBJECT, "role": "subject", "matched_authority": subject, "confidence": Decimal("0.96"), "status": AuthorityLinkSuggestion.Status.PENDING},
        )

        ReportDefinition.objects.update_or_create(
            code="demo_collection_health",
            defaults={"name": "Demo collection health", "description": "Portfolio demo report for circulation, acquisitions, ERM, and repository.", "required_permission": ""},
        )
        ReportRun.objects.update_or_create(
            code="demo_collection_health",
            name="Demo collection health",
            defaults={"status": ReportRun.Status.COMPLETED, "requested_by": staff, "record_count": 6, "result_json": {"open_loans": 1, "ready_holds": 1, "active_resources": 1}, "started_at": now - timedelta(minutes=20), "completed_at": now - timedelta(minutes=19)},
        )

        rebuild_all_indexes()
        dq_run = run_data_quality_checks(actor=staff)

        content_type = ContentType.objects.get_for_model(Instance)
        AuditLog.objects.get_or_create(
            action="portfolio_demo_seeded",
            entity_type=content_type,
            entity_id=str(instance.id),
            defaults={"actor": staff, "before": {}, "after": {"title": instance.title_statement, "data_quality_run": str(dq_run.id)}, "ip_address": "127.0.0.1", "user_agent": "seed_portfolio_demo"},
        )

        self.stdout.write(self.style.SUCCESS("Seeded LibraCore portfolio demo data."))
        self.stdout.write("Staff login: demo_staff / demo_staff_pass")
        self.stdout.write("Reader login: demo_reader / demo_reader_pass")

    def _authority(self, authority_type, label, *, source, control_number, uri, variants):
        authority, _ = AuthorityRecord.objects.update_or_create(
            source=source,
            control_number=control_number,
            defaults={"authority_type": authority_type, "entity_uri": uri, "status": AuthorityRecord.Status.AUTHORIZED},
        )
        AccessPoint.objects.update_or_create(
            authority=authority,
            kind=AccessPoint.Kind.AUTHORIZED,
            label=label,
            defaults={"is_preferred": True, "language": "zh-Hant", "script": "Hant", "normalized_label": label.lower()},
        )
        for variant in variants:
            AccessPoint.objects.update_or_create(
                authority=authority,
                kind=AccessPoint.Kind.VARIANT,
                label=variant,
                defaults={"is_preferred": False, "normalized_label": variant.lower()},
            )
        ExternalIdentifier.objects.update_or_create(
            scheme=source,
            value=control_number,
            defaults={"authority": authority, "uri": uri},
        )
        return authority

