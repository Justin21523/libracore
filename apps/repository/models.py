from django.db import models

from apps.core.models import BaseModel


class DigitalObject(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        RESTRICTED = "restricted", "Restricted"
        WITHDRAWN = "withdrawn", "Withdrawn"

    title = models.CharField(max_length=512)
    bibliographic_record = models.ForeignKey(
        "catalog.BibliographicRecord",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="digital_objects",
    )
    dc_metadata = models.JSONField(default=dict, blank=True)
    rights_statement = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    oai_identifier = models.CharField(max_length=255, blank=True)

    class Meta:
        indexes = [models.Index(fields=["status"]), models.Index(fields=["oai_identifier"])]

    def __str__(self) -> str:
        return self.title


class FileAsset(BaseModel):
    digital_object = models.ForeignKey(
        DigitalObject, on_delete=models.CASCADE, related_name="file_assets"
    )
    file = models.FileField(upload_to="repository/")
    label = models.CharField(max_length=255, blank=True)
    mime_type = models.CharField(max_length=128, blank=True)
    size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    checksum_sha256 = models.CharField(max_length=64, blank=True)
    ocr_text = models.TextField(blank=True)
    access_level = models.CharField(max_length=64, default="public")

    class Meta:
        indexes = [models.Index(fields=["mime_type", "access_level"])]

    def __str__(self) -> str:
        return self.label or self.file.name
