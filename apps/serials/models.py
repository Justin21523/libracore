from django.db import models

from apps.core.models import BaseModel


class SerialTitle(BaseModel):
    instance = models.OneToOneField(
        "catalog.Instance",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="serial_title",
    )
    title = models.CharField(max_length=512)
    issn = models.CharField(max_length=32, blank=True)
    frequency = models.CharField(max_length=128, blank=True)
    holding = models.ForeignKey(
        "holdings.Holding",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="serial_titles",
    )
    current_volume = models.PositiveIntegerField(default=1)
    current_number = models.PositiveIntegerField(default=0)
    publication_pattern = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self) -> str:
        return self.title


class Subscription(BaseModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"

    serial_title = models.ForeignKey(
        SerialTitle, on_delete=models.CASCADE, related_name="subscriptions"
    )
    vendor = models.ForeignKey(
        "acquisitions.Vendor", null=True, blank=True, on_delete=models.SET_NULL
    )
    branch = models.ForeignKey("holdings.Branch", on_delete=models.PROTECT)
    location = models.ForeignKey("holdings.Location", on_delete=models.PROTECT)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    create_item_on_checkin = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    def __str__(self) -> str:
        return f"{self.serial_title} subscription"


class IssuePredictionPattern(BaseModel):
    class Frequency(models.TextChoices):
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"
        QUARTERLY = "quarterly", "Quarterly"
        ANNUAL = "annual", "Annual"

    subscription = models.OneToOneField(
        Subscription, on_delete=models.CASCADE, related_name="prediction_pattern"
    )
    frequency = models.CharField(
        max_length=16, choices=Frequency.choices, default=Frequency.MONTHLY
    )
    enumeration_captions = models.JSONField(default=list, blank=True)
    chronology_template = models.CharField(max_length=128, default="{year}-{month:02d}")
    next_volume = models.PositiveIntegerField(default=1)
    next_number = models.PositiveIntegerField(default=1)
    next_expected_at = models.DateField()
    issues_per_volume = models.PositiveIntegerField(default=12)
    pattern_data = models.JSONField(default=dict, blank=True)


class BoundVolume(BaseModel):
    serial_title = models.ForeignKey(
        SerialTitle, on_delete=models.CASCADE, related_name="bound_volumes"
    )
    holding = models.ForeignKey(
        "holdings.Holding", null=True, blank=True, on_delete=models.SET_NULL
    )
    item = models.ForeignKey("holdings.Item", null=True, blank=True, on_delete=models.SET_NULL)
    label = models.CharField(max_length=255)
    bound_at = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self) -> str:
        return self.label


class Issue(BaseModel):
    class Status(models.TextChoices):
        EXPECTED = "expected", "Expected"
        RECEIVED = "received", "Received"
        MISSING = "missing", "Missing"
        BOUND = "bound", "Bound"

    serial_title = models.ForeignKey(SerialTitle, on_delete=models.CASCADE, related_name="issues")
    subscription = models.ForeignKey(
        Subscription, null=True, blank=True, on_delete=models.SET_NULL, related_name="issues"
    )
    enumeration = models.CharField(max_length=128, blank=True)
    chronology = models.CharField(max_length=128, blank=True)
    expected_at = models.DateField(null=True, blank=True)
    received_at = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.EXPECTED)
    holding = models.ForeignKey(
        "holdings.Holding", null=True, blank=True, on_delete=models.SET_NULL, related_name="issues"
    )
    item = models.ForeignKey(
        "holdings.Item",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="serial_issues",
    )
    prediction_data = models.JSONField(default=dict, blank=True)
    claim_count = models.PositiveIntegerField(default=0)
    bound_volume = models.ForeignKey(
        BoundVolume, null=True, blank=True, on_delete=models.SET_NULL, related_name="issues"
    )

    class Meta:
        indexes = [models.Index(fields=["status", "expected_at"])]

    def __str__(self) -> str:
        return f"{self.serial_title} {self.enumeration} {self.chronology}".strip()


class SerialCheckInEvent(BaseModel):
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="checkin_events")
    checked_in_by = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="serial_checkins",
    )
    checked_in_at = models.DateTimeField(auto_now_add=True)
    barcode = models.CharField(max_length=128)
    item = models.ForeignKey("holdings.Item", null=True, blank=True, on_delete=models.SET_NULL)


class ClaimEvent(BaseModel):
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="claim_events")
    claimed_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="serial_claims"
    )
    claimed_at = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True)
