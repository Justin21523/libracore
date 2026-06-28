from __future__ import annotations

import hashlib
import mimetypes

from django.core.exceptions import PermissionDenied

from apps.core.audit import write_audit_log

from .models import DigitalObject, FileAsset

PUBLIC_ACCESS_LEVEL = "public"


def published_objects():
    return (
        DigitalObject.objects.filter(status=DigitalObject.Status.PUBLISHED)
        .select_related("bibliographic_record", "bibliographic_record__instance")
        .prefetch_related("file_assets")
    )


def public_file_assets(digital_object: DigitalObject):
    return digital_object.file_assets.filter(access_level=PUBLIC_ACCESS_LEVEL)


def can_access_file(user, asset: FileAsset) -> bool:
    if (
        asset.access_level == PUBLIC_ACCESS_LEVEL
        and asset.digital_object.status == DigitalObject.Status.PUBLISHED
    ):
        return True
    return bool(user and user.is_authenticated and user.is_staff)


def enrich_uploaded_asset(
    asset: FileAsset, *, actor=None, ip_address=None, user_agent=""
) -> FileAsset:
    if not asset.file:
        return asset
    asset.size_bytes = asset.file.size
    asset.mime_type = asset.mime_type or _guess_mime_type(asset.file.name)
    asset.checksum_sha256 = _sha256(asset.file)
    if asset.mime_type.startswith("text/") and not asset.ocr_text:
        asset.ocr_text = _read_text_asset(asset.file)
    asset.save(
        update_fields=["size_bytes", "mime_type", "checksum_sha256", "ocr_text", "updated_at"]
    )
    write_audit_log(
        action="repository_file_asset_enriched",
        entity=asset,
        after={
            "size_bytes": asset.size_bytes,
            "mime_type": asset.mime_type,
            "checksum_sha256": asset.checksum_sha256,
        },
        actor=actor,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return asset


def publish_object(
    obj: DigitalObject, *, actor=None, ip_address=None, user_agent=""
) -> DigitalObject:
    before = {"status": obj.status}
    obj.status = DigitalObject.Status.PUBLISHED
    if not obj.oai_identifier:
        obj.oai_identifier = f"oai:libracore:repository:{obj.id}"
    obj.save(update_fields=["status", "oai_identifier", "updated_at"])
    write_audit_log(
        action="digital_object_published",
        entity=obj,
        before=before,
        after={"status": obj.status, "oai_identifier": obj.oai_identifier},
        actor=actor,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return obj


def withdraw_object(
    obj: DigitalObject, *, actor=None, ip_address=None, user_agent=""
) -> DigitalObject:
    before = {"status": obj.status}
    obj.status = DigitalObject.Status.WITHDRAWN
    obj.save(update_fields=["status", "updated_at"])
    write_audit_log(
        action="digital_object_withdrawn",
        entity=obj,
        before=before,
        after={"status": obj.status},
        actor=actor,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return obj


def repository_index_values(instance) -> tuple[str, dict]:
    bib_ids = list(instance.bib_records.values_list("id", flat=True))
    objects = (
        DigitalObject.objects.filter(
            bibliographic_record_id__in=bib_ids,
            status=DigitalObject.Status.PUBLISHED,
        )
        .prefetch_related("file_assets")
        .all()
    )
    text_parts = []
    mime_types = set()
    access_levels = set()
    for obj in objects:
        metadata = obj.dc_metadata or {}
        text_parts.extend([obj.title, obj.rights_statement])
        for value in metadata.values():
            if isinstance(value, list):
                text_parts.extend(str(item) for item in value)
            else:
                text_parts.append(str(value))
        for asset in obj.file_assets.all():
            text_parts.extend([asset.label, asset.ocr_text])
            if asset.mime_type:
                mime_types.add(asset.mime_type)
            if asset.access_level:
                access_levels.add(asset.access_level)
    facets = {
        "repository_available": ["true"] if objects else [],
        "file_mime_type": sorted(mime_types),
        "file_access_level": sorted(access_levels),
    }
    return " ".join(part for part in text_parts if part), facets


def assert_download_allowed(user, asset: FileAsset):
    if not can_access_file(user, asset):
        raise PermissionDenied("File is not publicly available.")


def _guess_mime_type(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def _sha256(file_field) -> str:
    digest = hashlib.sha256()
    file_field.open("rb")
    try:
        for chunk in file_field.chunks():
            digest.update(chunk)
    finally:
        file_field.close()
    return digest.hexdigest()


def _read_text_asset(file_field) -> str:
    file_field.open("rb")
    try:
        return file_field.read().decode("utf-8", errors="replace")
    finally:
        file_field.close()
