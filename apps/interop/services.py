from __future__ import annotations

from uuid import UUID

from django.core.files.base import ContentFile
from django.utils import timezone

from apps.catalog.models import BibliographicRecord

from .metadata import (
    approved_bibliographic_records,
    csv_export,
    marcxml_collection,
    oai_dc_for_bib,
    oai_dc_string,
)
from .models import ExportJob

CONTENT_TYPES = {
    ExportJob.ExportType.MARCXML_BIB: "application/xml",
    ExportJob.ExportType.DUBLIN_CORE: "application/xml",
    ExportJob.ExportType.CSV_PATRONS: "text/csv",
    ExportJob.ExportType.CSV_ITEMS: "text/csv",
    ExportJob.ExportType.CSV_HOLDINGS: "text/csv",
    ExportJob.ExportType.CSV_ACQUISITIONS: "text/csv",
    ExportJob.ExportType.CSV_FEES: "text/csv",
}


def create_and_run_export_job(
    *, export_type: str, requested_by=None, parameters: dict | None = None
) -> ExportJob:
    job = ExportJob.objects.create(
        export_type=export_type,
        requested_by=requested_by if getattr(requested_by, "is_authenticated", False) else None,
        parameters=parameters or {},
    )
    return run_export_job(job)


def run_export_job(job: ExportJob) -> ExportJob:
    job.status = ExportJob.Status.RUNNING
    job.started_at = timezone.now()
    job.save(update_fields=["status", "started_at", "updated_at"])
    try:
        content, count, extension = _render_export(job)
        filename = f"{job.export_type}-{job.id}.{extension}"
        job.result_file.save(filename, ContentFile(content.encode("utf-8")), save=False)
        job.record_count = count
        job.status = ExportJob.Status.COMPLETED
        job.completed_at = timezone.now()
        job.save(
            update_fields=["result_file", "record_count", "status", "completed_at", "updated_at"]
        )
    except Exception as exc:  # noqa: BLE001
        job.status = ExportJob.Status.FAILED
        job.error_report = [{"detail": str(exc)}]
        job.completed_at = timezone.now()
        job.save(update_fields=["status", "error_report", "completed_at", "updated_at"])
    return job


def _render_export(job: ExportJob) -> tuple[str, int, str]:
    if job.export_type == ExportJob.ExportType.MARCXML_BIB:
        content, count = marcxml_collection(approved_bibliographic_records())
        return content, count, "xml"
    if job.export_type == ExportJob.ExportType.DUBLIN_CORE:
        records = approved_bibliographic_records()
        chunks = [oai_dc_string(oai_dc_for_bib(record)) for record in records]
        return "\n".join(chunks), len(chunks), "xml"
    if job.export_type.startswith("csv_"):
        content, count = csv_export(job.export_type)
        return content, count, "csv"
    raise ValueError(f"Unsupported export type: {job.export_type}")


def export_content_type(job: ExportJob) -> str:
    return CONTENT_TYPES.get(job.export_type, "application/octet-stream")


def bib_by_oai_identifier(identifier: str) -> BibliographicRecord | None:
    prefix = "oai:libracore:bib:"
    if not identifier.startswith(prefix):
        return None
    raw_id = identifier.removeprefix(prefix)
    try:
        UUID(raw_id)
    except ValueError:
        return None
    return BibliographicRecord.objects.filter(id=raw_id).first()
