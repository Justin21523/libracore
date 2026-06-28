from __future__ import annotations

import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class ActiveQuerySet(models.QuerySet):
    def active(self):
        return self.filter(deleted_at__isnull=True)


class ActiveManager(models.Manager):
    def get_queryset(self):
        return ActiveQuerySet(self.model, using=self._db).active()


class BaseModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = ActiveManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True


class AuditLog(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=64)
    entity_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    entity_id = models.CharField(max_length=64)
    entity = GenericForeignKey("entity_type", "entity_id")
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["action", "created_at"]),
            models.Index(fields=["entity_type", "entity_id"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.action} {self.entity_type_id}:{self.entity_id}"


class DataQualityRun(BaseModel):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RUNNING)
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="data_quality_runs",
    )
    issue_count = models.PositiveIntegerField(default=0)
    summary = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error_report = models.TextField(blank=True)

    class Meta:
        indexes = [models.Index(fields=["status", "started_at"])]
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.status} {self.started_at}"


class DataQualityIssue(BaseModel):
    class Severity(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        ERROR = "error", "Error"

    run = models.ForeignKey(DataQualityRun, on_delete=models.CASCADE, related_name="issues")
    code = models.CharField(max_length=96)
    severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.WARNING)
    message = models.CharField(max_length=512)
    entity_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL)
    entity_id = models.CharField(max_length=64, blank=True)
    entity_label = models.CharField(max_length=512, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["run", "code"]),
            models.Index(fields=["severity", "created_at"]),
            models.Index(fields=["entity_type", "entity_id"]),
        ]
        ordering = ["code", "entity_label"]

    def __str__(self) -> str:
        return f"{self.code}: {self.entity_label or self.entity_id}"
