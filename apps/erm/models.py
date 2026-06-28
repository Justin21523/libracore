from django.db import models

from apps.core.models import BaseModel


class License(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        EXPIRED = "expired", "Expired"
        CANCELLED = "cancelled", "Cancelled"

    name = models.CharField(max_length=255)
    licensor = models.CharField(max_length=255, blank=True)
    vendor = models.ForeignKey(
        "acquisitions.Vendor",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="licenses",
    )
    invoice = models.ForeignKey(
        "acquisitions.Invoice",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="licenses",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    starts_at = models.DateField(null=True, blank=True)
    ends_at = models.DateField(null=True, blank=True)
    renewal_notice_days = models.PositiveIntegerField(default=60)
    terms = models.JSONField(default=dict, blank=True)
    document = models.FileField(upload_to="licenses/", blank=True)
    notes = models.TextField(blank=True)

    def __str__(self) -> str:
        return self.name


class Platform(BaseModel):
    code = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    vendor = models.ForeignKey(
        "acquisitions.Vendor",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="platforms",
    )
    base_url = models.URLField(blank=True)
    admin_url = models.URLField(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        indexes = [models.Index(fields=["code"]), models.Index(fields=["name"])]

    def __str__(self) -> str:
        return self.name


class Package(BaseModel):
    class Status(models.TextChoices):
        TRIAL = "trial", "Trial"
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        CANCELLED = "cancelled", "Cancelled"

    name = models.CharField(max_length=255)
    platform = models.ForeignKey(
        Platform, null=True, blank=True, on_delete=models.SET_NULL, related_name="packages"
    )
    vendor = models.ForeignKey(
        "acquisitions.Vendor",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="packages",
    )
    license = models.ForeignKey(
        License, null=True, blank=True, on_delete=models.SET_NULL, related_name="packages"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.TRIAL)
    starts_at = models.DateField(null=True, blank=True)
    ends_at = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        indexes = [models.Index(fields=["status", "ends_at"]), models.Index(fields=["name"])]

    def __str__(self) -> str:
        return self.name


class LicenseTerm(BaseModel):
    class TermType(models.TextChoices):
        WALK_IN_USERS = "walk_in_users", "Walk-in users"
        REMOTE_ACCESS = "remote_access", "Remote access"
        INTERLIBRARY_LOAN = "interlibrary_loan", "Interlibrary loan"
        COURSE_RESERVES = "course_reserves", "Course reserves"
        CONCURRENT_USERS = "concurrent_users", "Concurrent users"

    license = models.ForeignKey(License, on_delete=models.CASCADE, related_name="license_terms")
    term_type = models.CharField(max_length=32, choices=TermType.choices)
    allowed = models.BooleanField(default=True)
    limit_value = models.CharField(max_length=128, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        unique_together = [("license", "term_type")]
        indexes = [models.Index(fields=["term_type", "allowed"])]

    def __str__(self) -> str:
        return f"{self.license}: {self.term_type}"


class ProxyConfig(BaseModel):
    code = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    proxy_prefix = models.URLField()
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    def __str__(self) -> str:
        return self.name


class ElectronicResource(BaseModel):
    class ResourceKind(models.TextChoices):
        DATABASE = "database", "Database"
        EJOURNAL = "ejournal", "Electronic journal"
        EBOOK = "ebook", "Electronic book"
        PACKAGE = "package", "Package"

    class Status(models.TextChoices):
        TRIAL = "trial", "Trial"
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        CANCELLED = "cancelled", "Cancelled"

    class ResourceMode(models.TextChoices):
        ONLINE = "online", "Online"
        HYBRID = "hybrid", "Hybrid"
        LOCAL = "local", "Local"

    instance = models.ForeignKey(
        "catalog.Instance",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="electronic_resources",
    )
    title = models.CharField(max_length=512)
    resource_kind = models.CharField(max_length=32, choices=ResourceKind.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.TRIAL)
    resource_mode = models.CharField(
        max_length=16, choices=ResourceMode.choices, default=ResourceMode.ONLINE
    )
    platform = models.CharField(max_length=255, blank=True)
    platform_ref = models.ForeignKey(
        Platform, null=True, blank=True, on_delete=models.SET_NULL, related_name="resources"
    )
    package = models.ForeignKey(
        Package, null=True, blank=True, on_delete=models.SET_NULL, related_name="resources"
    )
    access_url = models.URLField(blank=True)
    license = models.ForeignKey(
        License, null=True, blank=True, on_delete=models.SET_NULL, related_name="resources"
    )
    coverage = models.JSONField(default=dict, blank=True)
    authentication_method = models.CharField(max_length=128, blank=True)
    identifiers = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    is_public = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=["resource_kind", "is_active"]),
            models.Index(fields=["status", "is_public"]),
            models.Index(fields=["resource_mode"]),
            models.Index(fields=["title"]),
        ]

    def __str__(self) -> str:
        return self.title


class Coverage(BaseModel):
    class CoverageType(models.TextChoices):
        FULL_TEXT = "full_text", "Full text"
        ABSTRACTING = "abstracting", "Abstracting"
        INDEXING = "indexing", "Indexing"

    resource = models.ForeignKey(
        ElectronicResource, on_delete=models.CASCADE, related_name="coverages"
    )
    coverage_type = models.CharField(
        max_length=24, choices=CoverageType.choices, default=CoverageType.FULL_TEXT
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    embargo = models.CharField(max_length=128, blank=True)
    coverage_note = models.TextField(blank=True)

    class Meta:
        indexes = [models.Index(fields=["coverage_type", "start_date", "end_date"])]

    def __str__(self) -> str:
        return f"{self.resource} {self.start_date or ''}-{self.end_date or 'present'}"


class AccessUrl(BaseModel):
    resource = models.ForeignKey(
        ElectronicResource, on_delete=models.CASCADE, related_name="access_urls"
    )
    label = models.CharField(max_length=255)
    url = models.URLField()
    is_primary = models.BooleanField(default=False)
    requires_proxy = models.BooleanField(default=False)
    proxy_config = models.ForeignKey(
        ProxyConfig, null=True, blank=True, on_delete=models.SET_NULL, related_name="access_urls"
    )
    notes = models.TextField(blank=True)

    class Meta:
        indexes = [models.Index(fields=["is_primary", "requires_proxy"])]

    def __str__(self) -> str:
        return self.label
