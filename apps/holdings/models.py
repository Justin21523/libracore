from django.db import models

from apps.core.models import BaseModel


class Branch(BaseModel):
    code = models.SlugField(max_length=32, unique=True)
    name = models.CharField(max_length=255)
    address = models.TextField(blank=True)
    timezone = models.CharField(max_length=64, default="Asia/Taipei")
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.name


class Location(BaseModel):
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="locations")
    code = models.SlugField(max_length=64)
    name = models.CharField(max_length=255)
    shelving_area = models.CharField(max_length=255, blank=True)
    is_public = models.BooleanField(default=True)
    circulation_policy = models.CharField(max_length=64, blank=True)

    class Meta:
        unique_together = [("branch", "code")]

    def __str__(self) -> str:
        return f"{self.branch.code}:{self.name}"


class Holding(BaseModel):
    instance = models.ForeignKey("catalog.Instance", on_delete=models.CASCADE, related_name="holdings")
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="holdings")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="holdings")
    call_number = models.ForeignKey(
        "vocabularies.CallNumber", null=True, blank=True, on_delete=models.SET_NULL
    )
    public_note = models.TextField(blank=True)
    staff_note = models.TextField(blank=True)
    textual_holdings = models.TextField(blank=True)
    access_policy = models.CharField(max_length=128, blank=True)

    class Meta:
        indexes = [models.Index(fields=["branch", "location"])]

    def __str__(self) -> str:
        return f"{self.instance} @ {self.location}"


class Item(BaseModel):
    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        ON_LOAN = "on_loan", "On loan"
        ON_HOLD = "on_hold", "On hold"
        IN_PROCESS = "in_process", "In process"
        MISSING = "missing", "Missing"
        LOST = "lost", "Lost"
        WITHDRAWN = "withdrawn", "Withdrawn"

    holding = models.ForeignKey(Holding, on_delete=models.CASCADE, related_name="items")
    barcode = models.CharField(max_length=128, unique=True)
    copy_number = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.IN_PROCESS)
    inventory_number = models.CharField(max_length=128, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    acquired_at = models.DateField(null=True, blank=True)
    last_inventory_at = models.DateTimeField(null=True, blank=True)
    due_back_at = models.DateTimeField(null=True, blank=True)
    item_note = models.TextField(blank=True)

    class Meta:
        indexes = [models.Index(fields=["status"]), models.Index(fields=["barcode"])]

    def __str__(self) -> str:
        return self.barcode

