from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class CirculationPolicy(BaseModel):
    priority = models.PositiveIntegerField(default=100)
    name = models.CharField(max_length=255)
    patron_type = models.CharField(max_length=64, blank=True)
    branch = models.ForeignKey(
        "holdings.Branch", null=True, blank=True, on_delete=models.CASCADE, related_name="circulation_policies"
    )
    location = models.ForeignKey(
        "holdings.Location", null=True, blank=True, on_delete=models.CASCADE, related_name="circulation_policies"
    )
    resource_type = models.CharField(max_length=32, blank=True)
    loan_period_days = models.PositiveIntegerField(default=14)
    renewal_period_days = models.PositiveIntegerField(default=14)
    max_renewals = models.PositiveIntegerField(default=2)
    max_open_loans = models.PositiveIntegerField(default=20)
    max_holds = models.PositiveIntegerField(default=10)
    allow_holds = models.BooleanField(default=True)
    allow_renewal_when_holds = models.BooleanField(default=False)
    hold_shelf_days = models.PositiveIntegerField(default=7)
    overdue_grace_days = models.PositiveIntegerField(default=0)
    overdue_fee_per_day = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    max_overdue_fee = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    fee_block_threshold = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["priority", "name"]
        indexes = [
            models.Index(fields=["is_active", "priority"]),
            models.Index(fields=["patron_type", "resource_type"]),
        ]

    def __str__(self) -> str:
        return self.name


class BranchCalendarException(BaseModel):
    branch = models.ForeignKey(
        "holdings.Branch", on_delete=models.CASCADE, related_name="calendar_exceptions"
    )
    date = models.DateField()
    name = models.CharField(max_length=255)
    is_closed = models.BooleanField(default=True)

    class Meta:
        unique_together = [("branch", "date")]
        indexes = [models.Index(fields=["branch", "date", "is_closed"])]

    def __str__(self) -> str:
        return f"{self.branch.code} {self.date} {self.name}"


class Patron(BaseModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="patron")
    patron_type = models.CharField(max_length=64, default="standard")
    barcode = models.CharField(max_length=128, unique=True)
    expiry_date = models.DateField(null=True, blank=True)
    privacy_opt_in = models.BooleanField(default=False)
    home_branch = models.ForeignKey(
        "holdings.Branch", null=True, blank=True, on_delete=models.SET_NULL, related_name="patrons"
    )

    def __str__(self) -> str:
        return self.barcode


class Loan(BaseModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RETURNED = "returned", "Returned"
        LOST = "lost", "Lost"

    item = models.ForeignKey("holdings.Item", on_delete=models.PROTECT, related_name="loans")
    patron = models.ForeignKey(Patron, on_delete=models.PROTECT, related_name="loans")
    checked_out_at = models.DateTimeField(auto_now_add=True)
    due_at = models.DateTimeField()
    returned_at = models.DateTimeField(null=True, blank=True)
    anonymized_at = models.DateTimeField(null=True, blank=True)
    renew_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)

    class Meta:
        indexes = [models.Index(fields=["status", "due_at"])]

    def __str__(self) -> str:
        return f"{self.item} -> {self.patron}"


class HoldRequest(BaseModel):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        READY = "ready", "Ready"
        FULFILLED = "fulfilled", "Fulfilled"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"

    patron = models.ForeignKey(Patron, on_delete=models.CASCADE, related_name="hold_requests")
    instance = models.ForeignKey(
        "catalog.Instance", null=True, blank=True, on_delete=models.CASCADE, related_name="hold_requests"
    )
    item = models.ForeignKey(
        "holdings.Item", null=True, blank=True, on_delete=models.CASCADE, related_name="hold_requests"
    )
    pickup_location = models.ForeignKey("holdings.Location", on_delete=models.PROTECT)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    queue_position = models.PositiveIntegerField(default=1)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["status", "queue_position"])]


class FineFee(BaseModel):
    class FeeType(models.TextChoices):
        OVERDUE = "overdue", "Overdue"
        LOST_ITEM = "lost_item", "Lost item"
        MANUAL = "manual", "Manual"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        PAID = "paid", "Paid"
        WAIVED = "waived", "Waived"
        VOIDED = "voided", "Voided"

    patron = models.ForeignKey(Patron, on_delete=models.CASCADE, related_name="fees")
    loan = models.ForeignKey(Loan, null=True, blank=True, on_delete=models.SET_NULL, related_name="fees")
    fee_type = models.CharField(max_length=32, choices=FeeType.choices, default=FeeType.MANUAL)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    reason = models.CharField(max_length=128)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    original_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    balance_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    assessed_at = models.DateTimeField(null=True, blank=True)
    assessed_through = models.DateField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    waived_at = models.DateTimeField(null=True, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["patron", "status"]),
            models.Index(fields=["fee_type", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.patron} {self.reason} {self.balance_amount}"


class Payment(BaseModel):
    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        CARD = "card", "Card"
        TRANSFER = "transfer", "Transfer"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        POSTED = "posted", "Posted"
        VOIDED = "voided", "Voided"

    patron = models.ForeignKey(Patron, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    method = models.CharField(max_length=16, choices=Method.choices, default=Method.CASH)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="received_circulation_payments",
    )
    received_at = models.DateTimeField(auto_now_add=True)
    reference = models.CharField(max_length=128, blank=True)
    note = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.POSTED)

    class Meta:
        indexes = [models.Index(fields=["patron", "received_at"]), models.Index(fields=["status"])]

    def __str__(self) -> str:
        return f"{self.patron} {self.amount}"


class PaymentAllocation(BaseModel):
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="allocations")
    fine_fee = models.ForeignKey(FineFee, on_delete=models.PROTECT, related_name="payment_allocations")
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        unique_together = [("payment", "fine_fee")]


class FeeWaiver(BaseModel):
    fine_fee = models.ForeignKey(FineFee, on_delete=models.PROTECT, related_name="waivers")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    waived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="circulation_fee_waivers",
    )
    waived_at = models.DateTimeField(auto_now_add=True)
    reason = models.TextField()
