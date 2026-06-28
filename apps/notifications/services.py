from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.mail import send_mail
from django.db.models import Sum
from django.template import Context, Template
from django.utils import timezone

from apps.circulation.models import FineFee, HoldRequest, Loan, Patron
from apps.erm.services import licenses_due_for_notice

from .models import Notification, NotificationTemplate


@dataclass(frozen=True)
class GenerationStats:
    created: int = 0
    skipped: int = 0


DEFAULT_TEMPLATES = {
    ("due_soon", "in_app"): ("借閱即將到期", "{{ title }} 將於 {{ due_at }} 到期。"),
    ("due_soon", "email"): ("借閱即將到期", "{{ title }} 將於 {{ due_at }} 到期。"),
    ("overdue", "in_app"): ("借閱已逾期", "{{ title }} 已於 {{ due_at }} 到期。"),
    ("overdue", "email"): ("借閱已逾期", "{{ title }} 已於 {{ due_at }} 到期。"),
    ("hold_available", "in_app"): ("預約到館", "{{ title }} 已可取書，保留至 {{ expires_at }}。"),
    ("hold_available", "email"): ("預約到館", "{{ title }} 已可取書，保留至 {{ expires_at }}。"),
    ("fine_notice", "in_app"): ("費用通知", "您目前有 {{ balance }} 的未繳費用。"),
    ("fine_notice", "email"): ("費用通知", "您目前有 {{ balance }} 的未繳費用。"),
    ("license_expiry_staff", "in_app"): (
        "License 即將到期",
        "{{ name }} 將於 {{ ends_at }} 到期。",
    ),
    ("license_expiry_staff", "email"): ("License 即將到期", "{{ name }} 將於 {{ ends_at }} 到期。"),
}


def seed_default_templates() -> int:
    created = 0
    for (notification_type, channel), (subject, body) in DEFAULT_TEMPLATES.items():
        _, was_created = NotificationTemplate.objects.get_or_create(
            code=f"{notification_type}-{channel}",
            defaults={
                "notification_type": notification_type,
                "channel": channel,
                "subject_template": subject,
                "body_template": body,
                "is_active": True,
            },
        )
        created += int(was_created)
    return created


def generate_notifications(
    notification_type: str | None = None, as_of=None, dry_run: bool = False
) -> dict:
    as_of = as_of or timezone.now()
    seed_default_templates()
    generators = {
        NotificationTemplate.NotificationType.DUE_SOON: generate_due_soon_notifications,
        NotificationTemplate.NotificationType.OVERDUE: generate_overdue_notifications,
        NotificationTemplate.NotificationType.HOLD_AVAILABLE: generate_hold_available_notifications,
        NotificationTemplate.NotificationType.FINE_NOTICE: generate_fine_notifications,
        NotificationTemplate.NotificationType.LICENSE_EXPIRY_STAFF: (
            generate_license_expiry_notifications
        ),
    }
    selected = [notification_type] if notification_type else list(generators)
    results = {}
    for selected_type in selected:
        stats = generators[selected_type](as_of=as_of, dry_run=dry_run)
        results[selected_type] = {"created": stats.created, "skipped": stats.skipped}
    return results


def generate_due_soon_notifications(*, as_of=None, dry_run: bool = False) -> GenerationStats:
    as_of = as_of or timezone.now()
    until = as_of + timezone.timedelta(days=3)
    loans = (
        Loan.objects.filter(status=Loan.Status.OPEN, due_at__gte=as_of, due_at__lte=until)
        .select_related("patron__user", "item__holding__instance")
        .order_by("due_at")
    )
    return _create_for_objects(
        loans,
        NotificationTemplate.NotificationType.DUE_SOON,
        lambda loan: loan.patron,
        lambda loan: {
            "title": loan.item.holding.instance.title_statement,
            "due_at": timezone.localtime(loan.due_at).strftime("%Y-%m-%d"),
        },
        as_of=as_of,
        dry_run=dry_run,
    )


def generate_overdue_notifications(*, as_of=None, dry_run: bool = False) -> GenerationStats:
    as_of = as_of or timezone.now()
    loans = (
        Loan.objects.filter(status=Loan.Status.OPEN, due_at__lt=as_of)
        .select_related("patron__user", "item__holding__instance")
        .order_by("due_at")
    )
    return _create_for_objects(
        loans,
        NotificationTemplate.NotificationType.OVERDUE,
        lambda loan: loan.patron,
        lambda loan: {
            "title": loan.item.holding.instance.title_statement,
            "due_at": timezone.localtime(loan.due_at).strftime("%Y-%m-%d"),
        },
        as_of=as_of,
        dry_run=dry_run,
    )


def generate_hold_available_notifications(*, as_of=None, dry_run: bool = False) -> GenerationStats:
    as_of = as_of or timezone.now()
    holds = (
        HoldRequest.objects.filter(status=HoldRequest.Status.READY)
        .select_related("patron__user", "instance", "item__holding__instance")
        .order_by("created_at")
    )
    return _create_for_objects(
        holds,
        NotificationTemplate.NotificationType.HOLD_AVAILABLE,
        lambda hold: hold.patron,
        lambda hold: {
            "title": hold.instance.title_statement
            if hold.instance_id
            else hold.item.holding.instance.title_statement,
            "expires_at": timezone.localtime(hold.expires_at).strftime("%Y-%m-%d")
            if hold.expires_at
            else "",
        },
        as_of=as_of,
        dry_run=dry_run,
    )


def generate_fine_notifications(*, as_of=None, dry_run: bool = False) -> GenerationStats:
    as_of = as_of or timezone.now()
    patrons = (
        Patron.objects.filter(fees__status=FineFee.Status.OPEN, fees__balance_amount__gt=0)
        .select_related("user")
        .annotate(open_balance=Sum("fees__balance_amount"))
        .distinct()
    )
    return _create_for_objects(
        patrons,
        NotificationTemplate.NotificationType.FINE_NOTICE,
        lambda patron: patron,
        lambda patron: {"balance": str(patron.open_balance)},
        as_of=as_of,
        dry_run=dry_run,
    )


def generate_license_expiry_notifications(*, as_of=None, dry_run: bool = False) -> GenerationStats:
    as_of = as_of or timezone.now()
    licenses = licenses_due_for_notice(today=timezone.localtime(as_of).date())
    staff_users = get_user_model().objects.filter(is_staff=True, is_active=True)
    created = 0
    skipped = 0
    for license_obj in licenses:
        for user in staff_users:
            stats = _create_notifications(
                recipient_user=user,
                patron=None,
                target=license_obj,
                notification_type=NotificationTemplate.NotificationType.LICENSE_EXPIRY_STAFF,
                context={"name": license_obj.name, "ends_at": license_obj.ends_at.isoformat()},
                as_of=as_of,
                dry_run=dry_run,
            )
            created += stats.created
            skipped += stats.skipped
    return GenerationStats(created=created, skipped=skipped)


def send_pending_notifications(limit: int | None = None) -> dict:
    queryset = Notification.objects.filter(
        channel=NotificationTemplate.Channel.EMAIL,
        status=Notification.Status.PENDING,
    ).select_related("recipient_user")
    if limit:
        queryset = queryset[:limit]
    sent = 0
    failed = 0
    for notification in queryset:
        try:
            send_mail(
                notification.subject,
                notification.body,
                None,
                [notification.recipient_user.email],
                fail_silently=False,
            )
        except Exception as exc:  # noqa: BLE001
            notification.status = Notification.Status.FAILED
            notification.failure_reason = str(exc)
            notification.save(update_fields=["status", "failure_reason", "updated_at"])
            failed += 1
        else:
            notification.status = Notification.Status.SENT
            notification.sent_at = timezone.now()
            notification.save(update_fields=["status", "sent_at", "updated_at"])
            sent += 1
    return {"sent": sent, "failed": failed}


def mark_notification_read(notification: Notification) -> Notification:
    notification.status = Notification.Status.READ
    notification.read_at = timezone.now()
    notification.save(update_fields=["status", "read_at", "updated_at"])
    return notification


def _create_for_objects(
    objects, notification_type, patron_getter, context_getter, *, as_of, dry_run: bool
) -> GenerationStats:
    created = 0
    skipped = 0
    for obj in objects:
        patron = patron_getter(obj)
        stats = _create_notifications(
            recipient_user=patron.user,
            patron=patron,
            target=obj,
            notification_type=notification_type,
            context=context_getter(obj),
            as_of=as_of,
            dry_run=dry_run,
        )
        created += stats.created
        skipped += stats.skipped
    return GenerationStats(created=created, skipped=skipped)


def _create_notifications(
    *,
    recipient_user,
    patron,
    target,
    notification_type,
    context: dict,
    as_of,
    dry_run: bool,
) -> GenerationStats:
    channels = [NotificationTemplate.Channel.IN_APP]
    if recipient_user.email:
        channels.append(NotificationTemplate.Channel.EMAIL)
    created = 0
    skipped = 0
    for channel in channels:
        dedupe_key = _dedupe_key(notification_type, channel, recipient_user.id, target, as_of)
        if Notification.objects.filter(dedupe_key=dedupe_key).exists():
            skipped += 1
            continue
        if dry_run:
            created += 1
            continue
        template = _template_for(notification_type, channel)
        subject, body = _render_template(template, context)
        Notification.objects.create(
            recipient_user=recipient_user,
            patron=patron,
            notification_type=notification_type,
            channel=channel,
            status=Notification.Status.SENT
            if channel == NotificationTemplate.Channel.IN_APP
            else Notification.Status.PENDING,
            subject=subject,
            body=body,
            context=context,
            target_type=ContentType.objects.get_for_model(target.__class__),
            target_id=str(target.id),
            dedupe_key=dedupe_key,
            sent_at=timezone.now() if channel == NotificationTemplate.Channel.IN_APP else None,
        )
        created += 1
    return GenerationStats(created=created, skipped=skipped)


def _template_for(notification_type, channel) -> NotificationTemplate:
    template = NotificationTemplate.objects.filter(
        notification_type=notification_type,
        channel=channel,
        is_active=True,
    ).first()
    if template:
        return template
    subject, body = DEFAULT_TEMPLATES[(notification_type, channel)]
    return NotificationTemplate(
        notification_type=notification_type,
        channel=channel,
        subject_template=subject,
        body_template=body,
    )


def _render_template(template: NotificationTemplate, context: dict) -> tuple[str, str]:
    django_context = Context(context, autoescape=False)
    subject = Template(template.subject_template).render(django_context).strip()
    body = Template(template.body_template).render(django_context).strip()
    return subject, body


def _dedupe_key(notification_type, channel, user_id, target, as_of) -> str:
    date_key = timezone.localtime(as_of).date().isoformat()
    target_type = ContentType.objects.get_for_model(target.__class__).app_label
    target_model = ContentType.objects.get_for_model(target.__class__).model
    return (
        f"{notification_type}:{channel}:{user_id}:"
        f"{target_type}.{target_model}:{target.id}:{date_key}"
    )
