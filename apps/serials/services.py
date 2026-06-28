from __future__ import annotations

from dataclasses import dataclass

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.utils import timezone

from apps.core.models import AuditLog
from apps.holdings.models import Holding, Item

from .models import (
    BoundVolume,
    ClaimEvent,
    Issue,
    SerialCheckInEvent,
    SerialTitle,
    Subscription,
)
from .prediction import advance_pattern, issue_labels


class SerialError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ActorContext:
    actor: object | None = None
    ip_address: str | None = None
    user_agent: str = ""


@transaction.atomic
def generate_expected_issues(
    *, subscription_id, count: int, actor_context: ActorContext | None = None
) -> list[Issue]:
    actor_context = actor_context or ActorContext()
    if count <= 0:
        raise SerialError("invalid_count", "Issue generation count must be positive.")
    subscription = (
        Subscription.objects.select_for_update()
        .select_related("serial_title")
        .get(id=subscription_id)
    )
    try:
        pattern = subscription.prediction_pattern
    except ObjectDoesNotExist:
        raise SerialError(
            "prediction_pattern_required", "Subscription requires an issue prediction pattern."
        )
    issues = []
    holding = _ensure_serial_holding(subscription)
    for _ in range(count):
        enumeration, chronology, data = issue_labels(pattern)
        issue = Issue.objects.create(
            serial_title=subscription.serial_title,
            subscription=subscription,
            enumeration=enumeration,
            chronology=chronology,
            expected_at=pattern.next_expected_at,
            holding=holding,
            prediction_data=data,
        )
        issues.append(issue)
        advance_pattern(pattern)
    _audit("serial_expected_issues_generated", subscription, {}, {"count": count}, actor_context)
    return issues


@transaction.atomic
def check_in_issue(*, issue_id, actor_context: ActorContext | None = None) -> Issue:
    actor_context = actor_context or ActorContext()
    issue = (
        Issue.objects.select_for_update()
        .select_related("subscription", "serial_title", "holding")
        .get(id=issue_id)
    )
    if issue.status == Issue.Status.RECEIVED:
        raise SerialError("issue_already_received", "Issue is already received.")
    if not issue.subscription_id and not issue.holding_id:
        raise SerialError(
            "subscription_or_holding_required",
            "Issue requires a subscription or holding for check-in.",
        )
    holding = issue.holding or _ensure_serial_holding(issue.subscription)
    barcode = _next_serial_barcode()
    item = Item.objects.create(
        holding=holding,
        barcode=barcode,
        status=Item.Status.IN_PROCESS,
        acquired_at=timezone.localdate(),
    )
    SerialCheckInEvent.objects.create(
        issue=issue,
        checked_in_by=actor_context.actor
        if getattr(actor_context.actor, "is_authenticated", False)
        else None,
        barcode=barcode,
        item=item,
    )
    before = {"status": issue.status}
    issue.status = Issue.Status.RECEIVED
    issue.received_at = timezone.localdate()
    issue.holding = holding
    issue.item = item
    issue.save(update_fields=["status", "received_at", "holding", "item", "updated_at"])
    _update_textual_holdings(issue.serial_title)
    _audit(
        "serial_issue_checked_in",
        issue,
        before,
        {"status": issue.status, "barcode": barcode},
        actor_context,
    )
    return issue


@transaction.atomic
def mark_issue_missing(*, issue_id, actor_context: ActorContext | None = None) -> Issue:
    actor_context = actor_context or ActorContext()
    issue = Issue.objects.select_for_update().get(id=issue_id)
    before = {"status": issue.status}
    issue.status = Issue.Status.MISSING
    issue.save(update_fields=["status", "updated_at"])
    _audit("serial_issue_marked_missing", issue, before, {"status": issue.status}, actor_context)
    return issue


@transaction.atomic
def claim_issue(
    *, issue_id, note: str = "", actor_context: ActorContext | None = None
) -> ClaimEvent:
    actor_context = actor_context or ActorContext()
    issue = Issue.objects.select_for_update().get(id=issue_id)
    event = ClaimEvent.objects.create(
        issue=issue,
        claimed_by=actor_context.actor
        if getattr(actor_context.actor, "is_authenticated", False)
        else None,
        note=note,
    )
    issue.claim_count += 1
    issue.save(update_fields=["claim_count", "updated_at"])
    _audit(
        "serial_issue_claimed",
        event,
        {},
        {"issue": str(issue.id), "claim_count": issue.claim_count},
        actor_context,
    )
    return event


@transaction.atomic
def bind_issues(
    *, issue_ids: list, label: str, actor_context: ActorContext | None = None
) -> BoundVolume:
    actor_context = actor_context or ActorContext()
    issues = list(
        Issue.objects.select_for_update()
        .select_related("serial_title", "holding")
        .filter(id__in=issue_ids)
    )
    if not issues:
        raise SerialError("issues_required", "At least one issue is required for binding.")
    serial_title = issues[0].serial_title
    holding = issues[0].holding
    if holding is None:
        raise SerialError("holding_required", "Issues must have a holding before binding.")
    item = Item.objects.create(
        holding=holding,
        barcode=_next_serial_barcode(prefix="BND"),
        status=Item.Status.IN_PROCESS,
        acquired_at=timezone.localdate(),
    )
    bound = BoundVolume.objects.create(
        serial_title=serial_title,
        holding=holding,
        item=item,
        label=label,
        bound_at=timezone.localdate(),
    )
    for issue in issues:
        issue.status = Issue.Status.BOUND
        issue.bound_volume = bound
        issue.save(update_fields=["status", "bound_volume", "updated_at"])
    _update_textual_holdings(serial_title)
    _audit("serial_issues_bound", bound, {}, {"count": len(issues), "label": label}, actor_context)
    return bound


def _ensure_serial_holding(subscription: Subscription) -> Holding:
    serial = subscription.serial_title
    if serial.holding_id:
        return serial.holding
    if serial.instance_id:
        holding, _ = Holding.objects.get_or_create(
            instance=serial.instance,
            branch=subscription.branch,
            location=subscription.location,
            defaults={"public_note": "Serial subscription holding"},
        )
        serial.holding = holding
        serial.save(update_fields=["holding", "updated_at"])
        return holding
    raise SerialError(
        "serial_instance_required", "Serial title must be linked to an Instance to create holdings."
    )


def _next_serial_barcode(prefix: str = "SER") -> str:
    today = timezone.localdate().strftime("%Y%m%d")
    count = Item.objects.filter(barcode__startswith=f"{prefix}-{today}").count() + 1
    return f"{prefix}-{today}-{count:05d}"


def _update_textual_holdings(serial_title: SerialTitle) -> None:
    if not serial_title.holding_id:
        return
    received = serial_title.issues.filter(
        status__in=[Issue.Status.RECEIVED, Issue.Status.BOUND]
    ).order_by("received_at", "enumeration")
    latest = received.last()
    serial_title.holding.textual_holdings = (
        f"Latest received: {latest.enumeration} {latest.chronology}".strip() if latest else ""
    )
    serial_title.holding.save(update_fields=["textual_holdings", "updated_at"])


def _audit(action: str, entity, before: dict, after: dict, actor_context: ActorContext) -> None:
    AuditLog.objects.create(
        actor=actor_context.actor
        if getattr(actor_context.actor, "is_authenticated", False)
        else None,
        action=action,
        entity_type=ContentType.objects.get_for_model(entity.__class__),
        entity_id=str(entity.id),
        before=before,
        after=after,
        ip_address=actor_context.ip_address,
        user_agent=actor_context.user_agent,
    )
