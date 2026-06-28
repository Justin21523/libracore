from django.db import models

from apps.core.models import BaseModel


class MarcImportBatch(BaseModel):
    class ImportFormat(models.TextChoices):
        ISO2709 = "iso2709", "ISO2709"
        MARCXML = "marcxml", "MARCXML"
        JSON = "json", "JSON MARC"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PARSED = "parsed", "Parsed"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    source = models.CharField(max_length=128, blank=True)
    import_format = models.CharField(max_length=16, choices=ImportFormat.choices)
    filename = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    submitted_by = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="marc_import_batches",
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    record_count = models.PositiveIntegerField(default=0)
    valid_count = models.PositiveIntegerField(default=0)
    invalid_count = models.PositiveIntegerField(default=0)
    conflict_count = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["source", "import_format"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.filename or self.id} ({self.import_format})"


class MarcImportRecord(BaseModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PARSED = "parsed", "Parsed"
        INVALID = "invalid", "Invalid"
        CONFLICT = "conflict", "Conflict"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    batch = models.ForeignKey(MarcImportBatch, on_delete=models.CASCADE, related_name="records")
    sequence = models.PositiveIntegerField()
    format_type = models.CharField(
        max_length=32,
        choices=[
            ("bibliographic", "Bibliographic"),
            ("authority", "Authority"),
            ("holdings", "Holdings"),
        ],
        default="bibliographic",
    )
    raw_payload = models.TextField(blank=True)
    parsed_json = models.JSONField(default=dict, blank=True)
    mapped_json = models.JSONField(default=dict, blank=True)
    validation_errors = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    control_number = models.CharField(max_length=128, blank=True)
    conflict_reason = models.TextField(blank=True)
    marc_record = models.ForeignKey(
        "marc.MarcRecord",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="import_records",
    )
    bibliographic_record = models.ForeignKey(
        "catalog.BibliographicRecord",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="import_records",
    )
    authority_record = models.ForeignKey(
        "authorities.AuthorityRecord",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="import_records",
    )
    holding = models.ForeignKey(
        "holdings.Holding",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="marc_import_records",
    )
    resolution_action = models.CharField(max_length=32, blank=True)
    resolved_by = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="resolved_marc_import_records",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("batch", "sequence")]
        indexes = [
            models.Index(fields=["batch", "status"]),
            models.Index(fields=["format_type", "status"]),
            models.Index(fields=["control_number"]),
        ]
        ordering = ["sequence"]

    def __str__(self) -> str:
        return f"{self.batch_id} #{self.sequence}"


class MarcMatchCandidate(BaseModel):
    class TargetType(models.TextChoices):
        BIBLIOGRAPHIC = "bibliographic", "Bibliographic record"
        AUTHORITY = "authority", "Authority record"
        HOLDING = "holding", "Holding"
        INSTANCE = "instance", "Instance"

    import_record = models.ForeignKey(
        MarcImportRecord, on_delete=models.CASCADE, related_name="match_candidates"
    )
    target_type = models.CharField(max_length=32, choices=TargetType.choices)
    target_id = models.CharField(max_length=64)
    match_rule = models.CharField(max_length=96)
    confidence = models.PositiveIntegerField(default=0)
    reason = models.CharField(max_length=512)
    payload = models.JSONField(default=dict, blank=True)
    selected = models.BooleanField(default=False)

    class Meta:
        unique_together = [("import_record", "target_type", "target_id", "match_rule")]
        indexes = [
            models.Index(fields=["import_record", "confidence"]),
            models.Index(fields=["target_type", "target_id"]),
        ]
        ordering = ["-confidence", "match_rule"]

    def __str__(self) -> str:
        return f"{self.import_record_id} -> {self.target_type}:{self.target_id}"


class AuthorityLinkSuggestion(BaseModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        CREATED = "created", "Created provisional authority"

    import_record = models.ForeignKey(
        MarcImportRecord, on_delete=models.CASCADE, related_name="authority_suggestions"
    )
    marc_tag = models.CharField(max_length=8)
    label = models.CharField(max_length=512)
    authority_type = models.CharField(max_length=32)
    role = models.CharField(max_length=64, blank=True)
    matched_authority = models.ForeignKey(
        "authorities.AuthorityRecord",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="marc_import_suggestions",
    )
    confidence = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    note = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["import_record", "status"]),
            models.Index(fields=["label", "authority_type"]),
        ]

    def __str__(self) -> str:
        return self.label


class MarcRecord(BaseModel):
    class FormatType(models.TextChoices):
        BIBLIOGRAPHIC = "bibliographic", "Bibliographic"
        AUTHORITY = "authority", "Authority"
        HOLDINGS = "holdings", "Holdings"

    class ValidationStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        VALID = "valid", "Valid"
        INVALID = "invalid", "Invalid"

    bibliographic_record = models.ForeignKey(
        "catalog.BibliographicRecord",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="marc_records",
    )
    authority_record = models.ForeignKey(
        "authorities.AuthorityRecord",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="marc_records",
    )
    holding = models.ForeignKey(
        "holdings.Holding",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="marc_records",
    )
    format_type = models.CharField(max_length=32, choices=FormatType.choices)
    raw_iso2709 = models.BinaryField(null=True, blank=True)
    marcxml = models.TextField(blank=True)
    parsed_json = models.JSONField(default=dict, blank=True)
    leader = models.CharField(max_length=24, blank=True)
    control_number = models.CharField(max_length=128, blank=True)
    source = models.CharField(max_length=128, blank=True)
    validation_status = models.CharField(
        max_length=16, choices=ValidationStatus.choices, default=ValidationStatus.PENDING
    )
    validation_errors = models.JSONField(default=list, blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["format_type", "control_number"]),
            models.Index(fields=["validation_status"]),
        ]

    def __str__(self) -> str:
        return f"{self.format_type}:{self.control_number or self.id}"
