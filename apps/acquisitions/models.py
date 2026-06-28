from django.db import models

from apps.core.models import BaseModel


class Vendor(BaseModel):
    code = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    contact = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self) -> str:
        return self.name


class Fund(BaseModel):
    code = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    fiscal_year = models.CharField(max_length=16)
    allocated_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=8, default="TWD")
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return f"{self.code} {self.fiscal_year}"


class PurchaseRequest(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        ORDERED = "ordered", "Ordered"

    title = models.CharField(max_length=512)
    requester = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="purchase_requests",
    )
    vendor = models.ForeignKey(
        Vendor, null=True, blank=True, on_delete=models.SET_NULL, related_name="purchase_requests"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    isbn = models.CharField(max_length=32, blank=True)
    publisher = models.CharField(max_length=255, blank=True)
    publication_date = models.CharField(max_length=64, blank=True)
    estimated_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    notes = models.TextField(blank=True)

    def __str__(self) -> str:
        return self.title


class AcquisitionOrder(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ORDERED = "ordered", "Ordered"
        PARTIALLY_RECEIVED = "partially_received", "Partially received"
        RECEIVED = "received", "Received"
        CANCELLED = "cancelled", "Cancelled"

    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="orders")
    purchase_request = models.ForeignKey(
        PurchaseRequest, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders"
    )
    order_number = models.CharField(max_length=128, unique=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.DRAFT)
    ordered_at = models.DateField(null=True, blank=True)
    currency = models.CharField(max_length=8, default="TWD")
    notes = models.TextField(blank=True)

    def __str__(self) -> str:
        return self.order_number


class AcquisitionOrderLine(BaseModel):
    class ReceivingStatus(models.TextChoices):
        NOT_RECEIVED = "not_received", "Not received"
        PARTIALLY_RECEIVED = "partially_received", "Partially received"
        RECEIVED = "received", "Received"
        CANCELLED = "cancelled", "Cancelled"

    order = models.ForeignKey(AcquisitionOrder, on_delete=models.CASCADE, related_name="lines")
    instance = models.ForeignKey(
        "catalog.Instance", null=True, blank=True, on_delete=models.SET_NULL
    )
    title = models.CharField(max_length=512)
    isbn = models.CharField(max_length=32, blank=True)
    publisher = models.CharField(max_length=255, blank=True)
    publication_date = models.CharField(max_length=64, blank=True)
    branch = models.ForeignKey("holdings.Branch", null=True, blank=True, on_delete=models.SET_NULL)
    location = models.ForeignKey(
        "holdings.Location", null=True, blank=True, on_delete=models.SET_NULL
    )
    call_number = models.ForeignKey(
        "vocabularies.CallNumber", null=True, blank=True, on_delete=models.SET_NULL
    )
    fund = models.ForeignKey(
        Fund, null=True, blank=True, on_delete=models.SET_NULL, related_name="order_lines"
    )
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    fund_code = models.CharField(max_length=64, blank=True)
    received_quantity = models.PositiveIntegerField(default=0)
    cancelled_quantity = models.PositiveIntegerField(default=0)
    receiving_status = models.CharField(
        max_length=24, choices=ReceivingStatus.choices, default=ReceivingStatus.NOT_RECEIVED
    )

    def __str__(self) -> str:
        return self.title


class ReceivingEvent(BaseModel):
    order_line = models.ForeignKey(
        AcquisitionOrderLine, on_delete=models.CASCADE, related_name="receiving_events"
    )
    quantity = models.PositiveIntegerField()
    barcodes = models.JSONField(default=list, blank=True)
    received_by = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="acquisition_receiving_events",
    )
    received_at = models.DateTimeField(auto_now_add=True)
    branch = models.ForeignKey("holdings.Branch", on_delete=models.PROTECT)
    location = models.ForeignKey("holdings.Location", on_delete=models.PROTECT)
    created_items = models.ManyToManyField(
        "holdings.Item", blank=True, related_name="receiving_events"
    )


class Invoice(BaseModel):
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="invoices")
    invoice_number = models.CharField(max_length=128)
    order = models.ForeignKey(
        AcquisitionOrder, null=True, blank=True, on_delete=models.SET_NULL, related_name="invoices"
    )
    issued_at = models.DateField(null=True, blank=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=8, default="TWD")
    match_status = models.CharField(max_length=24, default="pending")

    class Meta:
        unique_together = [("vendor", "invoice_number")]


class InvoiceLine(BaseModel):
    class MatchStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        MATCHED = "matched", "Matched"
        REVIEW = "review", "Review"

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    order_line = models.ForeignKey(
        AcquisitionOrderLine, on_delete=models.PROTECT, related_name="invoice_lines"
    )
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    tax = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)
    match_status = models.CharField(
        max_length=16, choices=MatchStatus.choices, default=MatchStatus.PENDING
    )


class FundTransaction(BaseModel):
    class TransactionType(models.TextChoices):
        ALLOCATION = "allocation", "Allocation"
        ENCUMBRANCE = "encumbrance", "Encumbrance"
        EXPENDITURE = "expenditure", "Expenditure"
        RELEASE = "release", "Release"
        ADJUSTMENT = "adjustment", "Adjustment"

    fund = models.ForeignKey(Fund, on_delete=models.CASCADE, related_name="transactions")
    transaction_type = models.CharField(max_length=24, choices=TransactionType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    order_line = models.ForeignKey(
        AcquisitionOrderLine,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="fund_transactions",
    )
    invoice_line = models.ForeignKey(
        InvoiceLine,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="fund_transactions",
    )
    note = models.TextField(blank=True)
