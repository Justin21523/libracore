from __future__ import annotations

from django.utils import timezone

from apps.circulation.models import FineFee, HoldRequest, Loan, Patron
from apps.circulation.services import (
    ActorContext,
    CirculationError,
    checkout_item,
    place_hold,
    renew_loan,
    return_item,
)
from apps.holdings.models import Item


def patron_status(barcode: str) -> dict:
    patron = Patron.objects.select_related("user").filter(barcode=barcode).first()
    if not patron:
        return _error("patron_not_found", "Patron not found.")
    return {
        "ok": True,
        "patron": _patron_dict(patron),
        "open_loans": patron.loans.filter(status=Loan.Status.OPEN).count(),
        "active_holds": patron.hold_requests.filter(
            status__in=[HoldRequest.Status.QUEUED, HoldRequest.Status.READY]
        ).count(),
        "fee_balance": str(_fee_balance(patron)),
    }


def item_status(barcode: str) -> dict:
    item = (
        Item.objects.select_related("holding__instance", "holding__location")
        .filter(barcode=barcode)
        .first()
    )
    if not item:
        return _error("item_not_found", "Item not found.")
    return {"ok": True, "item": _item_dict(item)}


def checkout(
    patron_barcode: str, item_barcode: str, actor_context: ActorContext | None = None
) -> dict:
    patron = Patron.objects.filter(barcode=patron_barcode).first()
    item = Item.objects.filter(barcode=item_barcode).first()
    if not patron:
        return _error("patron_not_found", "Patron not found.")
    if not item:
        return _error("item_not_found", "Item not found.")
    try:
        loan = checkout_item(item_id=item.id, patron_id=patron.id, actor_context=actor_context)
    except CirculationError as exc:
        return _error(exc.code, str(exc))
    return {"ok": True, "loan": _loan_dict(loan)}


def checkin(item_barcode: str, actor_context: ActorContext | None = None) -> dict:
    item = Item.objects.filter(barcode=item_barcode).first()
    if not item:
        return _error("item_not_found", "Item not found.")
    loan = Loan.objects.filter(item=item, status=Loan.Status.OPEN).first()
    if not loan:
        return _error("loan_not_found", "No open loan for item.")
    try:
        returned = return_item(loan_id=loan.id, actor_context=actor_context)
    except CirculationError as exc:
        return _error(exc.code, str(exc))
    return {"ok": True, "loan": _loan_dict(returned), "item": _item_dict(returned.item)}


def renew(
    patron_barcode: str, item_barcode: str, actor_context: ActorContext | None = None
) -> dict:
    patron = Patron.objects.filter(barcode=patron_barcode).first()
    item = Item.objects.filter(barcode=item_barcode).first()
    if not patron:
        return _error("patron_not_found", "Patron not found.")
    if not item:
        return _error("item_not_found", "Item not found.")
    loan = Loan.objects.filter(patron=patron, item=item, status=Loan.Status.OPEN).first()
    if not loan:
        return _error("loan_not_found", "No open loan for patron and item.")
    try:
        renewed = renew_loan(loan_id=loan.id, actor_context=actor_context)
    except CirculationError as exc:
        return _error(exc.code, str(exc))
    return {"ok": True, "loan": _loan_dict(renewed)}


def hold(
    patron_barcode: str,
    *,
    pickup_location_id,
    item_barcode: str | None = None,
    instance_id=None,
    actor_context: ActorContext | None = None,
) -> dict:
    patron = Patron.objects.filter(barcode=patron_barcode).first()
    if not patron:
        return _error("patron_not_found", "Patron not found.")
    item = Item.objects.filter(barcode=item_barcode).first() if item_barcode else None
    try:
        hold_request = place_hold(
            patron_id=patron.id,
            pickup_location_id=pickup_location_id,
            instance_id=instance_id,
            item_id=item.id if item else None,
            actor_context=actor_context,
        )
    except CirculationError as exc:
        return _error(exc.code, str(exc))
    return {"ok": True, "hold": {"id": str(hold_request.id), "status": hold_request.status}}


def _patron_dict(patron: Patron) -> dict:
    return {"id": str(patron.id), "barcode": patron.barcode, "username": patron.user.username}


def _item_dict(item: Item) -> dict:
    return {
        "id": str(item.id),
        "barcode": item.barcode,
        "status": item.status,
        "title": item.holding.instance.title_statement,
        "due_back_at": item.due_back_at.isoformat() if item.due_back_at else None,
    }


def _loan_dict(loan: Loan) -> dict:
    return {
        "id": str(loan.id),
        "status": loan.status,
        "due_at": timezone.localtime(loan.due_at).isoformat(),
        "patron": loan.patron.barcode,
        "item": loan.item.barcode,
    }


def _fee_balance(patron: Patron):
    return sum(fee.balance_amount for fee in patron.fees.filter(status=FineFee.Status.OPEN))


def _error(code: str, message: str) -> dict:
    return {"ok": False, "code": code, "message": message}
