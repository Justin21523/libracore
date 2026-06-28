from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.core.models import BaseModel


class NotificationTemplate(BaseModel):
    class NotificationType(models.TextChoices):
        DUE_SOON = "due_soon", "Due soon"
        OVERDUE = "overdue", "Overdue"
        HOLD_AVAILABLE = "hold_available", "Hold available"
        FINE_NOTICE = "fine_notice", "Fine notice"
        LICENSE_EXPIRY_STAFF = "license_expiry_staff", "License expiry staff"

    class Channel(models.TextChoices):
        IN_APP = "in_app", "In app"
        EMAIL = "email", "Email"

    code = models.SlugField(max_length=128, unique=True)
    notification_type = models.CharField(max_length=32, choices=NotificationType.choices)
    channel = models.CharField(max_length=16, choices=Channel.choices)
    subject_template = models.CharField(max_length=255)
    body_template = models.TextField()
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=["notification_type", "channel", "is_active"]),
        ]

    def __str__(self) -> str:
        return self.code


class Notification(BaseModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        READ = "read", "Read"

    recipient_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    patron = models.ForeignKey(
        "circulation.Patron",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    notification_type = models.CharField(
        max_length=32, choices=NotificationTemplate.NotificationType.choices
    )
    channel = models.CharField(max_length=16, choices=NotificationTemplate.Channel.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    subject = models.CharField(max_length=255)
    body = models.TextField()
    context = models.JSONField(default=dict, blank=True)
    target_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL)
    target_id = models.CharField(max_length=64, blank=True)
    target = GenericForeignKey("target_type", "target_id")
    dedupe_key = models.CharField(max_length=255, unique=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["recipient_user", "status", "created_at"]),
            models.Index(fields=["notification_type", "channel", "status"]),
            models.Index(fields=["target_type", "target_id"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.notification_type} {self.recipient_user_id}"
