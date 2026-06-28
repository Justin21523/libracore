from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.models import AuditLog
from apps.holdings.models import Item

from .models import FeeWaiver, FineFee, HoldRequest, Loan, Patron, Payment, PaymentAllocation
from .policies import next_open_due_at, resolve_policy


class CirculationError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ActorContext:
    actor: object | None = None
    ip_address: str | None = None
    user_agent: str = ""


ACTIVE_HOLD_STATUSES = [HoldRequest.Status.QUEUED, HoldRequest.Status.READY]


def checkout_item(*, item_id, patron_id, actor_context: ActorContext | None = None) -> Loan:
    actor_context = actor_context or ActorContext()
    with transaction.atomic():
        item = Item.objects.select_for_update().select_related(
            "holding", "holding__branch", "holding__location", "holding__instance"
        ).get(id=item_id)
        patron = Patron.objects.select_for_update().get(id=patron_id)
        policy = resolve_policy(patron, item)
        _assert_patron_can_borrow(patron, policy)

        ready_hold = _ready_hold_for_checkout(item, patron)
        if item.status != Item.Status.AVAILABLE and not ready_hold:
            raise CirculationError("item_not_available", "Item is not available for checkout.")

        open_loans = Loan.objects.filter(patron=patron, status=Loan.Status.OPEN).count()
        if open_loans >= policy.max_open_loans:
            raise CirculationError("loan_limit_exceeded", "Patron has reached the open loan limit.")

        now = timezone.now()
        due_at = next_open_due_at(now, item.holding.branch, policy.loan_period_days)
        loan = Loan.objects.create(item=item, patron=patron, due_at=due_at)
        before_item = {"status": item.status, "due_back_at": item.due_back_at.isoformat() if item.due_back_at else None}
        item.status = Item.Status.ON_LOAN
        item.due_back_at = due_at
        item.save(update_fields=["status", "due_back_at", "updated_at"])

        if ready_hold:
            before_hold = {"status": ready_hold.status, "item_id": str(ready_hold.item_id) if ready_hold.item_id else None}
            ready_hold.status = HoldRequest.Status.FULFILLED
            ready_hold.item = item
            ready_hold.save(update_fields=["status", "item", "updated_at"])
            _audit("hold_fulfilled", ready_hold, before_hold, {"status": ready_hold.status}, actor_context)
            _resequence_holds(item.holding.instance_id)

        _audit("checkout", loan, {}, {"loan_id": str(loan.id), "due_at": due_at.isoformat()}, actor_context)
        _audit("item_status_changed", item, before_item, {"status": item.status, "due_back_at": due_at.isoformat()}, actor_context)
        return loan


def return_item(*, loan_id, actor_context: ActorContext | None = None) -> Loan:
    actor_context = actor_context or ActorContext()
    with transaction.atomic():
        loan = Loan.objects.select_for_update().select_related(
            "item", "item__holding", "item__holding__branch", "item__holding__instance", "patron"
        ).get(id=loan_id)
        if loan.status != Loan.Status.OPEN:
            raise CirculationError("loan_not_open", "Only open loans can be returned.")

        assess_overdue_fee(loan=loan, actor_context=actor_context)
        item = Item.objects.select_for_update().get(id=loan.item_id)
        before_loan = {"status": loan.status, "returned_at": None}
        before_item = {"status": item.status, "due_back_at": item.due_back_at.isoformat() if item.due_back_at else None}
        now = timezone.now()
        loan.status = Loan.Status.RETURNED
        loan.returned_at = now
        loan.save(update_fields=["status", "returned_at", "updated_at"])

        next_hold = _next_hold_for_item(item)
        if next_hold:
            before_hold = {"status": next_hold.status, "item_id": str(next_hold.item_id) if next_hold.item_id else None}
            next_hold.status = HoldRequest.Status.READY
            next_hold.item = item
            policy = resolve_policy(next_hold.patron, item)
            next_hold.expires_at = next_open_due_at(now, item.holding.branch, policy.hold_shelf_days)
            next_hold.save(update_fields=["status", "item", "expires_at", "updated_at"])
            item.status = Item.Status.ON_HOLD
            _audit(
                "hold_ready",
                next_hold,
                before_hold,
                {"status": next_hold.status, "item_id": str(item.id), "expires_at": next_hold.expires_at.isoformat()},
                actor_context,
            )
        else:
            item.status = Item.Status.AVAILABLE
        item.due_back_at = None
        item.save(update_fields=["status", "due_back_at", "updated_at"])
        _resequence_holds(item.holding.instance_id)

        _audit("return", loan, before_loan, {"status": loan.status, "returned_at": now.isoformat()}, actor_context)
        _audit("item_status_changed", item, before_item, {"status": item.status, "due_back_at": None}, actor_context)
        return loan


def renew_loan(*, loan_id, actor_context: ActorContext | None = None) -> Loan:
    actor_context = actor_context or ActorContext()
    with transaction.atomic():
        loan = Loan.objects.select_for_update().select_related(
            "item", "item__holding", "item__holding__branch", "item__holding__instance", "patron"
        ).get(id=loan_id)
        if loan.status != Loan.Status.OPEN:
            raise CirculationError("loan_not_open", "Only open loans can be renewed.")
        policy = resolve_policy(loan.patron, loan.item)
        _assert_patron_can_borrow(loan.patron, policy)
        if loan.renew_count >= policy.max_renewals:
            raise CirculationError("renewal_limit_exceeded", "Loan has reached the renewal limit.")
        if not policy.allow_renewal_when_holds and _has_waiting_holds(loan.item):
            raise CirculationError("holds_block_renewal", "Waiting holds block renewal.")

        before = {"due_at": loan.due_at.isoformat(), "renew_count": loan.renew_count}
        base = max(timezone.now(), loan.due_at)
        loan.due_at = next_open_due_at(base, loan.item.holding.branch, policy.renewal_period_days)
        loan.renew_count += 1
        loan.item.due_back_at = loan.due_at
        loan.item.save(update_fields=["due_back_at", "updated_at"])
        loan.save(update_fields=["due_at", "renew_count", "updated_at"])
        _audit("renew", loan, before, {"due_at": loan.due_at.isoformat(), "renew_count": loan.renew_count}, actor_context)
        return loan


def place_hold(
    *,
    patron_id,
    pickup_location_id,
    instance_id=None,
    item_id=None,
    actor_context: ActorContext | None = None,
) -> HoldRequest:
    actor_context = actor_context or ActorContext()
    with transaction.atomic():
        patron = Patron.objects.select_for_update().get(id=patron_id)
        item = None
        if item_id:
            item = Item.objects.select_for_update().select_related("holding", "holding__instance").get(id=item_id)
            instance_id = instance_id or item.holding.instance_id
        if not instance_id:
            raise CirculationError("target_required", "Hold requires an instance or item.")

        sample_item = item or Item.objects.filter(holding__instance_id=instance_id).select_related(
            "holding", "holding__branch", "holding__location", "holding__instance"
        ).first()
        if sample_item:
            policy = resolve_policy(patron, sample_item)
            if not policy.allow_holds:
                raise CirculationError("holds_not_allowed", "Holds are not allowed by policy.")
            active_holds = HoldRequest.objects.filter(patron=patron, status__in=ACTIVE_HOLD_STATUSES).count()
            if active_holds >= policy.max_holds:
                raise CirculationError("hold_limit_exceeded", "Patron has reached the hold limit.")

        duplicate = HoldRequest.objects.filter(
            patron=patron,
            status__in=ACTIVE_HOLD_STATUSES,
        ).filter(models_or_instance(instance_id, item_id))
        if duplicate.exists():
            raise CirculationError("duplicate_hold", "Patron already has an active hold for this target.")

        queue_position = HoldRequest.objects.filter(
            instance_id=instance_id,
            status__in=ACTIVE_HOLD_STATUSES,
        ).count() + 1
        hold = HoldRequest.objects.create(
            patron=patron,
            instance_id=instance_id,
            item_id=item_id,
            pickup_location_id=pickup_location_id,
            queue_position=queue_position,
        )
        _audit("hold_placed", hold, {}, {"status": hold.status, "queue_position": hold.queue_position}, actor_context)
        return hold


def cancel_hold(*, hold_id, actor_context: ActorContext | None = None) -> HoldRequest:
    actor_context = actor_context or ActorContext()
    with transaction.atomic():
        hold = HoldRequest.objects.select_for_update().get(id=hold_id)
        if hold.status not in ACTIVE_HOLD_STATUSES:
            raise CirculationError("hold_not_active", "Only active holds can be cancelled.")
        before = {"status": hold.status}
        hold.status = HoldRequest.Status.CANCELLED
        hold.save(update_fields=["status", "updated_at"])
        _resequence_holds(hold.instance_id)
        _audit("hold_cancelled", hold, before, {"status": hold.status}, actor_context)
        return hold


def expire_ready_holds(*, as_of=None, actor_context: ActorContext | None = None) -> int:
    actor_context = actor_context or ActorContext()
    as_of = as_of or timezone.now()
    count = 0
    with transaction.atomic():
        holds = list(HoldRequest.objects.select_for_update().filter(status=HoldRequest.Status.READY, expires_at__lt=as_of))
        for hold in holds:
            before = {"status": hold.status}
            hold.status = HoldRequest.Status.EXPIRED
            hold.save(update_fields=["status", "updated_at"])
            if hold.item_id:
                item = Item.objects.select_for_update().get(id=hold.item_id)
                if item.status == Item.Status.ON_HOLD:
                    item.status = Item.Status.AVAILABLE
                    item.save(update_fields=["status", "updated_at"])
            _audit("hold_expired", hold, before, {"status": hold.status}, actor_context)
            _resequence_holds(hold.instance_id)
            count += 1
    return count


def assess_overdue_fee(*, loan: Loan | None = None, loan_id=None, as_of=None, actor_context: ActorContext | None = None) -> FineFee | None:
    actor_context = actor_context or ActorContext()
    as_of = as_of or timezone.now()
    with transaction.atomic():
        if loan is None:
            loan = Loan.objects.select_for_update().select_related(
                "item", "item__holding", "item__holding__branch", "item__holding__instance", "patron"
            ).get(id=loan_id)
        policy = resolve_policy(loan.patron, loan.item)
        overdue_days = (timezone.localtime(as_of).date() - timezone.localtime(loan.due_at).date()).days
        overdue_days = max(overdue_days - policy.overdue_grace_days, 0)
        if overdue_days <= 0 or policy.overdue_fee_per_day <= 0:
            return None
        amount = Decimal(overdue_days) * policy.overdue_fee_per_day
        if policy.max_overdue_fee > 0:
            amount = min(amount, policy.max_overdue_fee)
        amount = amount.quantize(Decimal("0.01"))

        fee, created = FineFee.objects.select_for_update().get_or_create(
            loan=loan,
            fee_type=FineFee.FeeType.OVERDUE,
            defaults={
                "patron": loan.patron,
                "reason": "Overdue item",
                "amount": amount,
                "original_amount": amount,
                "balance_amount": amount,
                "assessed_at": timezone.now(),
                "assessed_through": timezone.localtime(as_of).date(),
            },
        )
        before = _fee_snapshot(fee)
        if not created:
            paid_or_waived = max(fee.original_amount - fee.balance_amount, Decimal("0.00"))
            fee.amount = amount
            fee.original_amount = amount
            fee.balance_amount = max(amount - paid_or_waived, Decimal("0.00"))
            fee.assessed_through = timezone.localtime(as_of).date()
            fee.status = FineFee.Status.PAID if fee.balance_amount == 0 else FineFee.Status.OPEN
            fee.save(update_fields=["amount", "original_amount", "balance_amount", "assessed_through", "status", "updated_at"])
        _audit("fee_assessed", fee, {} if created else before, _fee_snapshot(fee), actor_context)
        return fee


def record_payment(
    *,
    patron_id,
    amount,
    method=Payment.Method.CASH,
    allocations=None,
    reference="",
    note="",
    actor_context: ActorContext | None = None,
) -> Payment:
    actor_context = actor_context or ActorContext()
    amount = Decimal(str(amount)).quantize(Decimal("0.01"))
    if amount <= 0:
        raise CirculationError("invalid_payment_amount", "Payment amount must be positive.")
    with transaction.atomic():
        patron = Patron.objects.select_for_update().get(id=patron_id)
        payment = Payment.objects.create(
            patron=patron,
            amount=amount,
            method=method,
            received_by=actor_context.actor if getattr(actor_context.actor, "is_authenticated", False) else None,
            reference=reference,
            note=note,
        )
        remaining = amount
        allocation_specs = allocations or _default_payment_allocations(patron, amount)
        for spec in allocation_specs:
            fee = FineFee.objects.select_for_update().get(id=spec["fine_fee_id"], patron=patron)
            allocation_amount = Decimal(str(spec["amount"])).quantize(Decimal("0.01"))
            if allocation_amount <= 0 or allocation_amount > remaining or allocation_amount > fee.balance_amount:
                raise CirculationError("invalid_allocation", "Payment allocation is invalid.")
            before = _fee_snapshot(fee)
            PaymentAllocation.objects.create(payment=payment, fine_fee=fee, amount=allocation_amount)
            fee.balance_amount -= allocation_amount
            if fee.balance_amount == 0:
                fee.status = FineFee.Status.PAID
                fee.paid_at = timezone.now()
            fee.save(update_fields=["balance_amount", "status", "paid_at", "updated_at"])
            _audit("fee_paid", fee, before, _fee_snapshot(fee), actor_context)
            remaining -= allocation_amount
        if remaining != 0:
            raise CirculationError("unallocated_payment", "Payment amount must be fully allocated.")
        _audit("payment_recorded", payment, {}, {"amount": str(payment.amount), "method": payment.method}, actor_context)
        return payment


def waive_fee(*, fine_fee_id, amount, reason, actor_context: ActorContext | None = None) -> FeeWaiver:
    actor_context = actor_context or ActorContext()
    amount = Decimal(str(amount)).quantize(Decimal("0.01"))
    if amount <= 0:
        raise CirculationError("invalid_waiver_amount", "Waiver amount must be positive.")
    with transaction.atomic():
        fee = FineFee.objects.select_for_update().get(id=fine_fee_id)
        if amount > fee.balance_amount:
            raise CirculationError("invalid_waiver_amount", "Waiver amount cannot exceed fee balance.")
        before = _fee_snapshot(fee)
        waiver = FeeWaiver.objects.create(
            fine_fee=fee,
            amount=amount,
            waived_by=actor_context.actor if getattr(actor_context.actor, "is_authenticated", False) else None,
            reason=reason,
        )
        fee.balance_amount -= amount
        if fee.balance_amount == 0:
            fee.status = FineFee.Status.WAIVED
            fee.waived_at = timezone.now()
        fee.save(update_fields=["balance_amount", "status", "waived_at", "updated_at"])
        _audit("fee_waived", fee, before, _fee_snapshot(fee), actor_context)
        return waiver


def _assert_patron_can_borrow(patron: Patron, policy) -> None:
    today = timezone.localdate()
    if patron.expiry_date and patron.expiry_date < today:
        raise CirculationError("patron_expired", "Patron account is expired.")
    if policy.fee_block_threshold > 0:
        balance = patron.fees.filter(status=FineFee.Status.OPEN).aggregate(total=Sum("balance_amount"))["total"] or Decimal("0")
        if balance >= policy.fee_block_threshold:
            raise CirculationError("fee_block", "Patron fee balance blocks circulation.")


def _ready_hold_for_checkout(item: Item, patron: Patron):
    return (
        HoldRequest.objects.select_for_update()
        .filter(patron=patron, status=HoldRequest.Status.READY)
        .filter(models_or_instance(item.holding.instance_id, item.id))
        .order_by("queue_position", "created_at")
        .first()
    )


def _next_hold_for_item(item: Item):
    return (
        HoldRequest.objects.select_for_update()
        .filter(status=HoldRequest.Status.QUEUED)
        .filter(models_or_instance(item.holding.instance_id, item.id))
        .order_by("queue_position", "created_at")
        .first()
    )


def _has_waiting_holds(item: Item) -> bool:
    return HoldRequest.objects.filter(status=HoldRequest.Status.QUEUED).filter(
        models_or_instance(item.holding.instance_id, item.id)
    ).exists()


def models_or_instance(instance_id, item_id):
    from django.db.models import Q

    query = Q(instance_id=instance_id, item__isnull=True)
    if item_id:
        query |= Q(item_id=item_id)
    return query


def _resequence_holds(instance_id) -> None:
    holds = HoldRequest.objects.filter(
        instance_id=instance_id,
        status__in=ACTIVE_HOLD_STATUSES,
    ).order_by("created_at", "id")
    for position, hold in enumerate(holds, start=1):
        if hold.queue_position != position:
            hold.queue_position = position
            hold.save(update_fields=["queue_position", "updated_at"])


def _default_payment_allocations(patron: Patron, amount: Decimal) -> list[dict]:
    allocations = []
    remaining = amount
    fees = patron.fees.filter(status=FineFee.Status.OPEN, balance_amount__gt=0).order_by("created_at", "id")
    for fee in fees:
        allocation = min(fee.balance_amount, remaining)
        allocations.append({"fine_fee_id": fee.id, "amount": allocation})
        remaining -= allocation
        if remaining == 0:
            break
    return allocations


def _fee_snapshot(fee: FineFee) -> dict:
    return {
        "status": fee.status,
        "amount": str(fee.amount),
        "original_amount": str(fee.original_amount),
        "balance_amount": str(fee.balance_amount),
    }


def _audit(action: str, entity, before: dict, after: dict, actor_context: ActorContext) -> None:
    AuditLog.objects.create(
        actor=actor_context.actor if getattr(actor_context.actor, "is_authenticated", False) else None,
        action=action,
        entity_type=ContentType.objects.get_for_model(entity.__class__),
        entity_id=str(entity.id),
        before=before,
        after=after,
        ip_address=actor_context.ip_address,
        user_agent=actor_context.user_agent,
    )

