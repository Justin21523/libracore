from __future__ import annotations

from collections import Counter

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from apps.catalog.models import BibliographicRecord, Instance, WorkAuthorityLink
from apps.erm.models import ElectronicResource, License
from apps.holdings.models import Holding, Item
from apps.marc.models import MarcRecord
from apps.repository.models import DigitalObject, FileAsset

from .audit import write_audit_log
from .models import DataQualityIssue, DataQualityRun


def run_data_quality_checks(actor=None) -> DataQualityRun:
    run = DataQualityRun.objects.create(
        started_by=actor if getattr(actor, "is_authenticated", False) else None
    )
    try:
        _catalog_checks(run)
        _marc_checks(run)
        _authority_checks(run)
        _holding_item_checks(run)
        _erm_checks(run)
        _repository_checks(run)
        counts = Counter(run.issues.values_list("code", flat=True))
        run.issue_count = sum(counts.values())
        run.summary = dict(counts)
        run.status = DataQualityRun.Status.COMPLETED
        run.completed_at = timezone.now()
        run.save(update_fields=["issue_count", "summary", "status", "completed_at", "updated_at"])
        write_audit_log(action="data_quality_run_completed", entity=run, actor=actor)
    except Exception as exc:  # noqa: BLE001
        run.status = DataQualityRun.Status.FAILED
        run.error_report = str(exc)
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "error_report", "completed_at", "updated_at"])
    return run


def _catalog_checks(run):
    for bib in BibliographicRecord.objects.select_related("work", "instance"):
        if not bib.work_id:
            _issue(run, "catalog.missing_work_link", bib, "書目未連結 Work。")
        if not bib.instance_id:
            _issue(run, "catalog.missing_instance_link", bib, "書目未連結 Instance。")
            continue
        instance = bib.instance
        if not instance.title_statement.strip():
            _issue(run, "catalog.missing_title", instance, "Instance 缺少題名。")
        if not _has_identifier(instance, "isbn") and not _has_identifier(instance, "issn"):
            _issue(run, "catalog.missing_isbn_issn", instance, "Instance 缺少 ISBN/ISSN。")
        if not instance.publisher or not instance.publication_date:
            _issue(run, "catalog.missing_publication_data", instance, "出版者或出版年缺漏。")


def _marc_checks(run):
    controls = Counter()
    for marc in MarcRecord.objects.all():
        controls[marc.control_number] += 1
        if marc.leader and len(marc.leader) != 24:
            _issue(run, "marc.invalid_leader", marc, "MARC leader 長度不是 24。")
        parsed = marc.parsed_json or {}
        fields = parsed.get("fields", [])
        tags = [field.get("tag") for field in fields if isinstance(field, dict)]
        if "001" not in tags and not marc.control_number:
            _issue(run, "marc.missing_001", marc, "MARC 缺少 001 control number。")
        if marc.format_type == MarcRecord.FormatType.BIBLIOGRAPHIC and "245" not in tags:
            _issue(run, "marc.missing_245", marc, "MARC Bibliographic 缺少 245 題名欄。")
    for control_number, count in controls.items():
        if control_number and count > 1:
            for marc in MarcRecord.objects.filter(control_number=control_number):
                _issue(
                    run,
                    "marc.duplicate_control_number",
                    marc,
                    f"MARC control number 重複：{control_number}",
                )


def _authority_checks(run):
    for instance in Instance.objects.select_related("work"):
        has_creator_text = bool(instance.responsibility_statement)
        if has_creator_text and not instance.contributors.exists():
            _issue(run, "authority.creator_unlinked", instance, "責任者文字未連結權威。")
        if not instance.work_id:
            continue
        has_subject_text = bool(instance.work.subjects.exists())
        linked_subject = WorkAuthorityLink.objects.filter(
            work=instance.work, role=WorkAuthorityLink.Role.SUBJECT
        ).exists()
        if has_subject_text and not linked_subject:
            _issue(run, "authority.subject_unlinked", instance.work, "主題詞未連結主題權威。")


def _holding_item_checks(run):
    for holding in Holding.objects.select_related("instance", "branch", "location"):
        if not holding.items.exists():
            _issue(run, "holdings.no_items", holding, "館藏沒有任何單冊。")
    for item in Item.objects.select_related("holding__instance"):
        if not item.barcode.strip():
            _issue(run, "item.blank_barcode", item, "單冊條碼空白。")
        stale_since = timezone.now() - timezone.timedelta(days=30)
        if item.status in [Item.Status.MISSING, Item.Status.LOST] and item.updated_at < stale_since:
            _issue(run, "item.problem_status_stale", item, "Missing/Lost 狀態超過 30 天。")


def _erm_checks(run):
    today = timezone.localdate()
    for license_obj in License.objects.filter(status=License.Status.ACTIVE, ends_at__lt=today):
        _issue(run, "erm.active_license_expired", license_obj, "Active license 已過期。")
    for resource in ElectronicResource.objects.prefetch_related("access_urls", "coverages"):
        if resource.is_public and resource.status == ElectronicResource.Status.ACTIVE:
            has_url = bool(resource.access_url) or resource.access_urls.exists()
            if not has_url:
                _issue(run, "erm.missing_access_url", resource, "公開電子資源缺少 access URL。")
            if not resource.coverages.exists() and not resource.coverage:
                _issue(run, "erm.missing_coverage", resource, "電子資源缺少 coverage。")
            for access_url in resource.access_urls.all():
                if access_url.requires_proxy and not access_url.proxy_config_id:
                    _issue(
                        run, "erm.proxy_config_missing", access_url, "需 proxy 但未設定 config。"
                    )


def _repository_checks(run):
    for obj in DigitalObject.objects.prefetch_related("file_assets"):
        metadata = obj.dc_metadata or {}
        if obj.status == DigitalObject.Status.PUBLISHED:
            if not obj.file_assets.filter(access_level="public").exists():
                _issue(run, "repository.no_public_file", obj, "Published 數位物件沒有公開檔案。")
            if not metadata.get("title") and not obj.title:
                _issue(run, "repository.missing_dc_title", obj, "數位物件缺少 DC title。")
    for asset in FileAsset.objects.select_related("digital_object"):
        if asset.access_level == "public" and not asset.checksum_sha256:
            _issue(run, "repository.public_file_missing_checksum", asset, "公開檔案缺少 checksum。")
        if asset.file and not asset.mime_type:
            _issue(run, "repository.file_missing_mime_type", asset, "檔案缺少 MIME type。")


def _issue(run, code: str, entity, message: str, severity=DataQualityIssue.Severity.WARNING):
    DataQualityIssue.objects.create(
        run=run,
        code=code,
        severity=severity,
        message=message,
        entity_type=ContentType.objects.get_for_model(entity.__class__),
        entity_id=str(entity.id),
        entity_label=str(entity),
    )


def _has_identifier(instance: Instance, scheme: str) -> bool:
    for identifier in instance.identifiers:
        if isinstance(identifier, dict) and identifier.get("scheme", "").lower() == scheme:
            return bool(identifier.get("value"))
    return False
