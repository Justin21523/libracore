from rest_framework import serializers

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


class CirculationPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = CirculationPolicy
        fields = "__all__"


class BranchCalendarExceptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = BranchCalendarException
        fields = "__all__"


class PatronSerializer(serializers.ModelSerializer):
    class Meta:
        model = Patron
        fields = "__all__"


class LoanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Loan
        fields = "__all__"


class HoldRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = HoldRequest
        fields = "__all__"


class FineFeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = FineFee
        fields = "__all__"


class PaymentAllocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentAllocation
        fields = "__all__"


class PaymentSerializer(serializers.ModelSerializer):
    allocations = PaymentAllocationSerializer(many=True, read_only=True)

    class Meta:
        model = Payment
        fields = "__all__"


class FeeWaiverSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeeWaiver
        fields = "__all__"


class CheckoutRequestSerializer(serializers.Serializer):
    item_id = serializers.UUIDField()
    patron_id = serializers.UUIDField()


class PlaceHoldRequestSerializer(serializers.Serializer):
    patron_id = serializers.UUIDField()
    pickup_location_id = serializers.UUIDField()
    instance_id = serializers.UUIDField(required=False)
    item_id = serializers.UUIDField(required=False)

    def validate(self, attrs):
        if not attrs.get("instance_id") and not attrs.get("item_id"):
            raise serializers.ValidationError("instance_id or item_id is required.")
        return attrs


class AssessOverdueRequestSerializer(serializers.Serializer):
    loan_id = serializers.UUIDField()


class PaymentAllocationInputSerializer(serializers.Serializer):
    fine_fee_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)


class PaymentRequestSerializer(serializers.Serializer):
    patron_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    method = serializers.ChoiceField(choices=Payment.Method.choices, default=Payment.Method.CASH)
    reference = serializers.CharField(required=False, allow_blank=True)
    note = serializers.CharField(required=False, allow_blank=True)
    allocations = PaymentAllocationInputSerializer(many=True, required=False)


class WaiveFeeRequestSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    reason = serializers.CharField()

