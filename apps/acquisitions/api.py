from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.core.api import BaseModelViewSet
from apps.core.permissions import AcquisitionsRolePermission

from .models import (
    AcquisitionOrder,
    AcquisitionOrderLine,
    Fund,
    FundTransaction,
    Invoice,
    InvoiceLine,
    PurchaseRequest,
    ReceivingEvent,
    Vendor,
)
from .serializers import (
    AcquisitionOrderLineSerializer,
    AcquisitionOrderSerializer,
    CancelOrderLineSerializer,
    FundSerializer,
    FundTransactionSerializer,
    InvoiceLineSerializer,
    InvoiceSerializer,
    PurchaseRequestSerializer,
    ReceiveOrderLineSerializer,
    ReceivingEventSerializer,
    VendorSerializer,
)
from .services import (
    AcquisitionError,
    ActorContext,
    approve_purchase_request,
    cancel_order_line,
    match_invoice,
    place_order,
    receive_order_line,
)


def _require_staff(request):
    if not request.user.is_authenticated or not request.user.is_staff:
        raise PermissionDenied("Staff permission is required.")


def _actor_context(request) -> ActorContext:
    return ActorContext(
        actor=request.user,
        ip_address=request.META.get("REMOTE_ADDR"),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )


def _error_response(exc: AcquisitionError):
    return Response({"code": exc.code, "detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class VendorViewSet(BaseModelViewSet):
    queryset = Vendor.objects.all()
    serializer_class = VendorSerializer
    permission_classes = [AcquisitionsRolePermission]
    search_fields = ["code", "name", "notes"]


class FundViewSet(BaseModelViewSet):
    queryset = Fund.objects.all()
    serializer_class = FundSerializer
    permission_classes = [AcquisitionsRolePermission]
    search_fields = ["code", "name", "fiscal_year"]


class FundTransactionViewSet(BaseModelViewSet):
    queryset = FundTransaction.objects.select_related("fund", "order_line", "invoice_line").all()
    serializer_class = FundTransactionSerializer
    permission_classes = [AcquisitionsRolePermission]
    search_fields = ["fund__code", "note"]


class PurchaseRequestViewSet(BaseModelViewSet):
    queryset = PurchaseRequest.objects.select_related("requester", "vendor").all()
    serializer_class = PurchaseRequestSerializer
    permission_classes = [AcquisitionsRolePermission]
    search_fields = ["title", "isbn", "publisher", "notes"]

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        _require_staff(request)
        request_obj = approve_purchase_request(request_id=pk, actor_context=_actor_context(request))
        return Response(self.get_serializer(request_obj).data)


class AcquisitionOrderViewSet(BaseModelViewSet):
    queryset = AcquisitionOrder.objects.select_related("vendor").all()
    serializer_class = AcquisitionOrderSerializer
    permission_classes = [AcquisitionsRolePermission]
    search_fields = ["order_number", "vendor__name", "notes"]

    @action(detail=True, methods=["post"])
    def place(self, request, pk=None):
        _require_staff(request)
        try:
            order = place_order(order_id=pk, actor_context=_actor_context(request))
        except AcquisitionError as exc:
            return _error_response(exc)
        return Response(self.get_serializer(order).data)


class AcquisitionOrderLineViewSet(BaseModelViewSet):
    queryset = AcquisitionOrderLine.objects.select_related("order", "instance").all()
    serializer_class = AcquisitionOrderLineSerializer
    permission_classes = [AcquisitionsRolePermission]
    search_fields = ["title", "fund_code", "instance__title_statement"]

    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        _require_staff(request)
        serializer = ReceiveOrderLineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            event = receive_order_line(
                order_line_id=pk, **serializer.validated_data, actor_context=_actor_context(request)
            )
        except AcquisitionError as exc:
            return _error_response(exc)
        return Response(ReceivingEventSerializer(event).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="cancel-line")
    def cancel_line(self, request, pk=None):
        _require_staff(request)
        serializer = CancelOrderLineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            line = cancel_order_line(
                order_line_id=pk,
                quantity=serializer.validated_data["quantity"],
                actor_context=_actor_context(request),
            )
        except AcquisitionError as exc:
            return _error_response(exc)
        return Response(self.get_serializer(line).data)


class ReceivingEventViewSet(BaseModelViewSet):
    queryset = ReceivingEvent.objects.select_related(
        "order_line", "received_by", "branch", "location"
    ).all()
    serializer_class = ReceivingEventSerializer
    permission_classes = [AcquisitionsRolePermission]
    search_fields = ["order_line__title", "barcodes"]


class InvoiceViewSet(BaseModelViewSet):
    queryset = Invoice.objects.select_related("vendor", "order").all()
    serializer_class = InvoiceSerializer
    permission_classes = [AcquisitionsRolePermission]
    search_fields = ["invoice_number", "vendor__name", "order__order_number"]

    @action(detail=True, methods=["post"])
    def match(self, request, pk=None):
        _require_staff(request)
        invoice = match_invoice(invoice_id=pk, actor_context=_actor_context(request))
        return Response(self.get_serializer(invoice).data)


class InvoiceLineViewSet(BaseModelViewSet):
    queryset = InvoiceLine.objects.select_related("invoice", "order_line").all()
    serializer_class = InvoiceLineSerializer
    permission_classes = [AcquisitionsRolePermission]
    search_fields = ["invoice__invoice_number", "order_line__title"]


def register(router):
    router.register("vendors", VendorViewSet, basename="vendor")
    router.register("funds", FundViewSet, basename="fund")
    router.register("fund-transactions", FundTransactionViewSet, basename="fund-transaction")
    router.register("purchase-requests", PurchaseRequestViewSet, basename="purchase-request")
    router.register("acquisition-orders", AcquisitionOrderViewSet, basename="acquisition-order")
    router.register(
        "acquisition-order-lines", AcquisitionOrderLineViewSet, basename="acquisition-order-line"
    )
    router.register("receiving-events", ReceivingEventViewSet, basename="receiving-event")
    router.register("invoices", InvoiceViewSet, basename="invoice")
    router.register("invoice-lines", InvoiceLineViewSet, basename="invoice-line")
