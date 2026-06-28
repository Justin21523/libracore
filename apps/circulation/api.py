from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.core.api import BaseModelViewSet, serializer_for
from apps.core.roles import ROLE_ADMIN, ROLE_CIRCULATION, user_has_role

from .models import (
    BranchCalendarException,
    CirculationPolicy,
    FeeWaiver,
    FineFee,
    HoldRequest,
    Loan,
    Patron,
    Payment,
    PaymentAllocation,
)
from .serializers import (
    AssessOverdueRequestSerializer,
    BranchCalendarExceptionSerializer,
    CheckoutRequestSerializer,
    CirculationPolicySerializer,
    FeeWaiverSerializer,
    FineFeeSerializer,
    HoldRequestSerializer,
    LoanSerializer,
    PatronSerializer,
    PaymentRequestSerializer,
    PaymentSerializer,
    PlaceHoldRequestSerializer,
    WaiveFeeRequestSerializer,
)
from .services import (
    ActorContext,
    CirculationError,
    assess_overdue_fee,
    cancel_hold,
    checkout_item,
    expire_ready_holds,
    place_hold,
    record_payment,
    renew_loan,
    return_item,
    waive_fee,
)


def _require_staff(request):
    if not user_has_role(request.user, ROLE_CIRCULATION):
        raise PermissionDenied("Circulation staff permission is required.")


def _require_admin(request):
    if not user_has_role(request.user, ROLE_ADMIN):
        raise PermissionDenied("Admin permission is required.")


def _actor_context(request) -> ActorContext:
    return ActorContext(
        actor=request.user,
        ip_address=request.META.get("REMOTE_ADDR"),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )


def _error_response(exc: CirculationError):
    return Response({"code": exc.code, "detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class CirculationPolicyViewSet(BaseModelViewSet):
    queryset = CirculationPolicy.objects.select_related("branch", "location").all()
    serializer_class = CirculationPolicySerializer
    search_fields = ["name", "patron_type", "resource_type"]

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        return [CirculationStaffPermission()]


class CirculationStaffPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        return user_has_role(request.user, ROLE_CIRCULATION)


class PatronSelfOrStaffPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        return user_has_role(request.user, ROLE_CIRCULATION)


class BranchCalendarExceptionViewSet(BaseModelViewSet):
    queryset = BranchCalendarException.objects.select_related("branch").all()
    serializer_class = BranchCalendarExceptionSerializer
    search_fields = ["branch__code", "name"]
    permission_classes = [CirculationStaffPermission]


class PatronViewSet(BaseModelViewSet):
    serializer_class = PatronSerializer
    permission_classes = [PatronSelfOrStaffPermission]
    search_fields = ["barcode", "user__username", "user__email"]

    def get_queryset(self):
        queryset = Patron.objects.select_related("user", "home_branch").all()
        if user_has_role(self.request.user, ROLE_CIRCULATION):
            return queryset
        return queryset.filter(user=self.request.user)


class LoanViewSet(BaseModelViewSet):
    serializer_class = LoanSerializer
    permission_classes = [PatronSelfOrStaffPermission]
    search_fields = ["item__barcode", "patron__barcode"]

    def get_queryset(self):
        queryset = Loan.objects.select_related("item", "patron", "patron__user").all()
        if user_has_role(self.request.user, ROLE_CIRCULATION):
            return queryset
        return queryset.filter(patron__user=self.request.user)

    @action(detail=True, methods=["post"], url_path="return-item")
    def return_item(self, request, pk=None):
        _require_staff(request)
        try:
            loan = return_item(loan_id=pk, actor_context=_actor_context(request))
        except CirculationError as exc:
            return _error_response(exc)
        return Response(self.get_serializer(loan).data)

    @action(detail=True, methods=["post"])
    def renew(self, request, pk=None):
        _require_staff(request)
        try:
            loan = renew_loan(loan_id=pk, actor_context=_actor_context(request))
        except CirculationError as exc:
            return _error_response(exc)
        return Response(self.get_serializer(loan).data)


class HoldRequestViewSet(BaseModelViewSet):
    serializer_class = HoldRequestSerializer
    permission_classes = [PatronSelfOrStaffPermission]
    search_fields = ["patron__barcode", "instance__title_statement", "item__barcode"]

    def get_queryset(self):
        queryset = HoldRequest.objects.select_related(
            "patron", "patron__user", "instance", "item", "pickup_location"
        ).all()
        if user_has_role(self.request.user, ROLE_CIRCULATION):
            return queryset
        return queryset.filter(patron__user=self.request.user)

    @action(detail=False, methods=["post"])
    def place(self, request):
        _require_staff(request)
        serializer = PlaceHoldRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            hold = place_hold(**serializer.validated_data, actor_context=_actor_context(request))
        except CirculationError as exc:
            return _error_response(exc)
        return Response(self.get_serializer(hold).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        _require_staff(request)
        try:
            hold = cancel_hold(hold_id=pk, actor_context=_actor_context(request))
        except CirculationError as exc:
            return _error_response(exc)
        return Response(self.get_serializer(hold).data)

    @action(detail=False, methods=["post"], url_path="expire-ready")
    def expire_ready(self, request):
        _require_staff(request)
        count = expire_ready_holds(actor_context=_actor_context(request))
        return Response({"expired": count})


class FineFeeViewSet(BaseModelViewSet):
    serializer_class = FineFeeSerializer
    permission_classes = [PatronSelfOrStaffPermission]
    search_fields = ["patron__barcode", "reason"]

    def get_queryset(self):
        queryset = FineFee.objects.select_related("patron", "patron__user", "loan").all()
        if user_has_role(self.request.user, ROLE_CIRCULATION):
            return queryset
        return queryset.filter(patron__user=self.request.user)

    @action(detail=False, methods=["post"], url_path="assess-overdue")
    def assess_overdue(self, request):
        _require_staff(request)
        serializer = AssessOverdueRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            fee = assess_overdue_fee(
                loan_id=serializer.validated_data["loan_id"],
                actor_context=_actor_context(request),
            )
        except CirculationError as exc:
            return _error_response(exc)
        if fee is None:
            return Response({"created": False, "detail": "No overdue fee assessed."})
        return Response(self.get_serializer(fee).data)

    @action(detail=True, methods=["post"])
    def waive(self, request, pk=None):
        _require_admin(request)
        serializer = WaiveFeeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            waiver = waive_fee(
                fine_fee_id=pk,
                amount=serializer.validated_data["amount"],
                reason=serializer.validated_data["reason"],
                actor_context=_actor_context(request),
            )
        except CirculationError as exc:
            return _error_response(exc)
        return Response(FeeWaiverSerializer(waiver).data, status=status.HTTP_201_CREATED)


class PaymentViewSet(BaseModelViewSet):
    serializer_class = PaymentSerializer
    permission_classes = [PatronSelfOrStaffPermission]
    search_fields = ["patron__barcode", "reference", "note"]

    def get_queryset(self):
        queryset = Payment.objects.select_related("patron", "patron__user", "received_by").all()
        if user_has_role(self.request.user, ROLE_CIRCULATION):
            return queryset
        return queryset.filter(patron__user=self.request.user)

    def create(self, request, *args, **kwargs):
        _require_staff(request)
        serializer = PaymentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payment = record_payment(
                **serializer.validated_data, actor_context=_actor_context(request)
            )
        except CirculationError as exc:
            return _error_response(exc)
        return Response(self.get_serializer(payment).data, status=status.HTTP_201_CREATED)


class PaymentAllocationViewSet(BaseModelViewSet):
    queryset = PaymentAllocation.objects.select_related("payment", "fine_fee").all()
    serializer_class = serializer_for(PaymentAllocation)
    permission_classes = [CirculationStaffPermission]


class FeeWaiverViewSet(BaseModelViewSet):
    queryset = FeeWaiver.objects.select_related("fine_fee", "waived_by").all()
    serializer_class = FeeWaiverSerializer
    permission_classes = [CirculationStaffPermission]


class CirculationActionsViewSet(viewsets.ViewSet):
    permission_classes = [CirculationStaffPermission]

    @action(detail=False, methods=["post"])
    def checkout(self, request):
        _require_staff(request)
        serializer = CheckoutRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            loan = checkout_item(**serializer.validated_data, actor_context=_actor_context(request))
        except CirculationError as exc:
            return _error_response(exc)
        return Response(LoanSerializer(loan).data, status=status.HTTP_201_CREATED)


def register(router):
    router.register("circulation", CirculationActionsViewSet, basename="circulation")
    router.register("circulation-policies", CirculationPolicyViewSet, basename="circulation-policy")
    router.register(
        "branch-calendar-exceptions",
        BranchCalendarExceptionViewSet,
        basename="branch-calendar-exception",
    )
    router.register("patrons", PatronViewSet, basename="patron")
    router.register("loans", LoanViewSet, basename="loan")
    router.register("hold-requests", HoldRequestViewSet, basename="hold-request")
    router.register("fine-fees", FineFeeViewSet, basename="fine-fee")
    router.register("payments", PaymentViewSet, basename="payment")
    router.register("payment-allocations", PaymentAllocationViewSet, basename="payment-allocation")
    router.register("fee-waivers", FeeWaiverViewSet, basename="fee-waiver")
