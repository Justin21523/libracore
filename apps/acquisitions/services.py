from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import BibliographicRecord, Instance, Work
from apps.core.models import AuditLog
from apps.holdings.models import Holding, Item

from .models import (
    AcquisitionOrder,
    AcquisitionOrderLine,
    FundTransaction,
    Invoice,
    InvoiceLine,
    PurchaseRequest,
    ReceivingEvent,
)


class AcquisitionError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ActorContext:
    actor: object | None = None
    ip_address: str | None = None
    user_agent: str = ""


@transaction.atomic
def approve_purchase_request(
    *, request_id, actor_context: ActorContext | None = None
) -> PurchaseRequest:
    actor_context = actor_context or ActorContext()
    request = PurchaseRequest.objects.select_for_update().get(id=request_id)
    before = {"status": request.status}
    request.status = PurchaseRequest.Status.APPROVED
    request.save(update_fields=["status", "updated_at"])
    _audit("purchase_request_approved", request, before, {"status": request.status}, actor_context)
    return request


@transaction.atomic
def place_order(*, order_id, actor_context: ActorContext | None = None) -> AcquisitionOrder:
    actor_context = actor_context or ActorContext()
    order = AcquisitionOrder.objects.select_for_update().prefetch_related("lines").get(id=order_id)
    if order.status not in [AcquisitionOrder.Status.DRAFT, AcquisitionOrder.Status.ORDERED]:
        raise AcquisitionError("invalid_order_status", "Only draft orders can be placed.")
    before = {"status": order.status}
    order.status = AcquisitionOrder.Status.ORDERED
    order.ordered_at = order.ordered_at or timezone.localdate()
    order.save(update_fields=["status", "ordered_at", "updated_at"])
    for line in order.lines.select_for_update():
        if line.fund_id and line.unit_price:
            FundTransaction.objects.get_or_create(
                fund=line.fund,
                transaction_type=FundTransaction.TransactionType.ENCUMBRANCE,
                order_line=line,
                defaults={"amount": _line_total(line), "note": f"Order {order.order_number}"},
            )
    if order.purchase_request_id:
        order.purchase_request.status = PurchaseRequest.Status.ORDERED
        order.purchase_request.save(update_fields=["status", "updated_at"])
    _audit("acquisition_order_placed", order, before, {"status": order.status}, actor_context)
    return order


@transaction.atomic
def receive_order_line(
    *,
    order_line_id,
    quantity: int,
    barcodes: list[str],
    branch_id=None,
    location_id=None,
    actor_context: ActorContext | None = None,
) -> ReceivingEvent:
    actor_context = actor_context or ActorContext()
    line = (
        AcquisitionOrderLine.objects.select_for_update()
        .select_related("order", "instance")
        .get(id=order_line_id)
    )
    if quantity <= 0:
        raise AcquisitionError("invalid_quantity", "Receiving quantity must be positive.")
    remaining = line.quantity - line.received_quantity - line.cancelled_quantity
    if quantity > remaining:
        raise AcquisitionError(
            "quantity_exceeds_remaining", "Receiving quantity exceeds remaining quantity."
        )
    if len(barcodes) != quantity or len(set(barcodes)) != len(barcodes):
        raise AcquisitionError(
            "barcode_mismatch", "Barcode count must equal quantity and be unique."
        )
    if Item.objects.filter(barcode__in=barcodes).exists():
        raise AcquisitionError("barcode_exists", "One or more barcodes already exist.")
    branch_id = branch_id or line.branch_id
    location_id = location_id or line.location_id
    if not branch_id or not location_id:
        raise AcquisitionError(
            "location_required", "Branch and location are required for receiving."
        )
    instance = line.instance or _create_simple_bibliographic_record(line)
    line.instance = instance
    holding, _ = Holding.objects.get_or_create(
        instance=instance,
        branch_id=branch_id,
        location_id=location_id,
        defaults={
            "call_number": line.call_number,
            "staff_note": f"Created from order {line.order.order_number}",
        },
    )
    event = ReceivingEvent.objects.create(
        order_line=line,
        quantity=quantity,
        barcodes=barcodes,
        received_by=actor_context.actor
        if getattr(actor_context.actor, "is_authenticated", False)
        else None,
        branch_id=branch_id,
        location_id=location_id,
    )
    for barcode in barcodes:
        item = Item.objects.create(
            holding=holding,
            barcode=barcode,
            status=Item.Status.IN_PROCESS,
            price=line.unit_price,
            acquired_at=timezone.localdate(),
        )
        event.created_items.add(item)
    line.received_quantity += quantity
    line.receiving_status = (
        AcquisitionOrderLine.ReceivingStatus.RECEIVED
        if line.received_quantity + line.cancelled_quantity >= line.quantity
        else AcquisitionOrderLine.ReceivingStatus.PARTIALLY_RECEIVED
    )
    line.save(update_fields=["instance", "received_quantity", "receiving_status", "updated_at"])
    _update_order_status(line.order)
    _audit(
        "acquisition_order_line_received",
        event,
        {},
        {"quantity": quantity, "barcodes": barcodes},
        actor_context,
    )
    return event


@transaction.atomic
def cancel_order_line(
    *, order_line_id, quantity: int, actor_context: ActorContext | None = None
) -> AcquisitionOrderLine:
    actor_context = actor_context or ActorContext()
    line = (
        AcquisitionOrderLine.objects.select_for_update()
        .select_related("order")
        .get(id=order_line_id)
    )
    remaining = line.quantity - line.received_quantity - line.cancelled_quantity
    if quantity <= 0 or quantity > remaining:
        raise AcquisitionError("invalid_cancel_quantity", "Cancel quantity is invalid.")
    before = {"cancelled_quantity": line.cancelled_quantity}
    line.cancelled_quantity += quantity
    line.receiving_status = (
        AcquisitionOrderLine.ReceivingStatus.CANCELLED
        if line.cancelled_quantity == line.quantity
        else line.receiving_status
    )
    line.save(update_fields=["cancelled_quantity", "receiving_status", "updated_at"])
    if line.fund_id and line.unit_price:
        FundTransaction.objects.create(
            fund=line.fund,
            transaction_type=FundTransaction.TransactionType.RELEASE,
            amount=Decimal(quantity) * line.unit_price,
            order_line=line,
            note="Cancelled order line quantity",
        )
    _update_order_status(line.order)
    _audit(
        "acquisition_order_line_cancelled",
        line,
        before,
        {"cancelled_quantity": line.cancelled_quantity},
        actor_context,
    )
    return line


@transaction.atomic
def match_invoice(*, invoice_id, actor_context: ActorContext | None = None) -> Invoice:
    actor_context = actor_context or ActorContext()
    invoice = (
        Invoice.objects.select_for_update().prefetch_related("lines__order_line").get(id=invoice_id)
    )
    review = False
    for line in invoice.lines.select_for_update():
        order_line = line.order_line
        expected = Decimal(line.quantity) * (order_line.unit_price or Decimal("0"))
        if line.quantity > order_line.received_quantity or line.line_total > expected + Decimal(
            "0.01"
        ):
            line.match_status = InvoiceLine.MatchStatus.REVIEW
            review = True
        else:
            line.match_status = InvoiceLine.MatchStatus.MATCHED
            if order_line.fund_id:
                FundTransaction.objects.get_or_create(
                    fund=order_line.fund,
                    transaction_type=FundTransaction.TransactionType.EXPENDITURE,
                    invoice_line=line,
                    defaults={
                        "amount": line.line_total,
                        "order_line": order_line,
                        "note": f"Invoice {invoice.invoice_number}",
                    },
                )
                FundTransaction.objects.get_or_create(
                    fund=order_line.fund,
                    transaction_type=FundTransaction.TransactionType.RELEASE,
                    invoice_line=line,
                    defaults={
                        "amount": line.line_total,
                        "order_line": order_line,
                        "note": "Release encumbrance",
                    },
                )
        line.save(update_fields=["match_status", "updated_at"])
    before = {"match_status": invoice.match_status}
    invoice.match_status = "review" if review else "matched"
    invoice.save(update_fields=["match_status", "updated_at"])
    _audit(
        "invoice_matched", invoice, before, {"match_status": invoice.match_status}, actor_context
    )
    return invoice


def _create_simple_bibliographic_record(line: AcquisitionOrderLine) -> Instance:
    work = Work.objects.create(primary_title=line.title)
    identifiers = [{"scheme": "isbn", "value": line.isbn}] if line.isbn else []
    instance = Instance.objects.create(
        work=work,
        title_statement=line.title,
        publisher=line.publisher,
        publication_date=line.publication_date,
        identifiers=identifiers,
    )
    BibliographicRecord.objects.create(
        source="acquisitions",
        control_number=f"ACQ-{line.id}",
        status=BibliographicRecord.Status.APPROVED,
        work=work,
        instance=instance,
        metadata={"created_from_order_line": str(line.id)},
    )
    return instance


def _line_total(line: AcquisitionOrderLine) -> Decimal:
    return Decimal(line.quantity) * (line.unit_price or Decimal("0"))


def _update_order_status(order: AcquisitionOrder) -> None:
    lines = list(order.lines.all())
    if not lines:
        return
    if all(line.received_quantity + line.cancelled_quantity >= line.quantity for line in lines):
        order.status = AcquisitionOrder.Status.RECEIVED
    elif any(line.received_quantity > 0 for line in lines):
        order.status = AcquisitionOrder.Status.PARTIALLY_RECEIVED
    order.save(update_fields=["status", "updated_at"])


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
