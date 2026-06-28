from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.circulation.models import Loan, Patron
from apps.notifications.models import Notification

from .models import AuditLog


@dataclass(frozen=True)
class RetentionResult:
    loans_anonymized: int = 0
    notifications_deleted: int = 0
    audit_logs_deleted: int = 0


def apply_retention_policy(
    *,
    apply: bool = False,
    loan_days: int = 365,
    notification_days: int = 180,
    audit_years: int = 7,
) -> RetentionResult:
    loan_cutoff = timezone.now() - timezone.timedelta(days=loan_days)
    notification_cutoff = timezone.now() - timezone.timedelta(days=notification_days)
    audit_cutoff = timezone.now() - timezone.timedelta(days=365 * audit_years)
    loan_queryset = Loan.objects.filter(
        status=Loan.Status.RETURNED,
        returned_at__lt=loan_cutoff,
        patron__privacy_opt_in=False,
        anonymized_at__isnull=True,
    )
    notification_queryset = Notification.objects.filter(
        status__in=[Notification.Status.SENT, Notification.Status.READ, Notification.Status.FAILED],
        updated_at__lt=notification_cutoff,
        deleted_at__isnull=True,
    )
    audit_queryset = AuditLog.objects.filter(created_at__lt=audit_cutoff)
    result = RetentionResult(
        loans_anonymized=loan_queryset.count(),
        notifications_deleted=notification_queryset.count(),
        audit_logs_deleted=audit_queryset.count(),
    )
    if not apply:
        return result
    anonymous = _anonymous_patron()
    loan_queryset.update(patron=anonymous, anonymized_at=timezone.now())
    notification_queryset.update(deleted_at=timezone.now())
    audit_queryset.delete()
    return result


def _anonymous_patron() -> Patron:
    user_model = get_user_model()
    user, _ = user_model.objects.get_or_create(
        username="anonymous-retention",
        defaults={"email": "anonymous-retention@libracore.local"},
    )
    patron, _ = Patron.objects.get_or_create(
        user=user,
        defaults={"barcode": "ANON-RETENTION", "patron_type": "anonymous"},
    )
    return patron
