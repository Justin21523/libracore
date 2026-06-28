from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class ExportJob(BaseModel):
    class ExportType(models.TextChoices):
        MARCXML_BIB = "marcxml_bib", "MARCXML bibliographic"
        DUBLIN_CORE = "dublin_core", "Dublin Core"
        CSV_PATRONS = "csv_patrons", "CSV patrons"
        CSV_ITEMS = "csv_items", "CSV items"
        CSV_HOLDINGS = "csv_holdings", "CSV holdings"
        CSV_ACQUISITIONS = "csv_acquisitions", "CSV acquisitions"
        CSV_FEES = "csv_fees", "CSV fees"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    export_type = models.CharField(max_length=32, choices=ExportType.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="export_jobs",
    )
    parameters = models.JSONField(default=dict, blank=True)
    result_file = models.FileField(upload_to="exports/", blank=True)
    record_count = models.PositiveIntegerField(default=0)
    error_report = models.JSONField(default=list, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["export_type", "status"]),
            models.Index(fields=["requested_by", "created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.export_type}:{self.status}"
