from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class ReportDefinition(BaseModel):
    code = models.CharField(max_length=96, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    query_spec = models.JSONField(default=dict, blank=True)
    required_permission = models.CharField(max_length=128, blank=True)

    def __str__(self) -> str:
        return self.name


class ReportRun(BaseModel):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    report_definition = models.ForeignKey(
        ReportDefinition,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="runs",
    )
    code = models.CharField(max_length=96)
    name = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RUNNING)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="report_runs",
    )
    parameters = models.JSONField(default=dict, blank=True)
    result_json = models.JSONField(default=dict, blank=True)
    csv_file = models.FileField(upload_to="reports/", blank=True)
    record_count = models.PositiveIntegerField(default=0)
    error_report = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["code", "status"]),
            models.Index(fields=["requested_by", "created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.code} {self.status}"
