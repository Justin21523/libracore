from rest_framework import serializers

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


class VendorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vendor
        fields = "__all__"


class FundSerializer(serializers.ModelSerializer):
    class Meta:
        model = Fund
        fields = "__all__"


class FundTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = FundTransaction
        fields = "__all__"


class PurchaseRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseRequest
        fields = "__all__"


class AcquisitionOrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = AcquisitionOrder
        fields = "__all__"


class AcquisitionOrderLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = AcquisitionOrderLine
        fields = "__all__"


class ReceivingEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReceivingEvent
        fields = "__all__"


class InvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = "__all__"


class InvoiceLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceLine
        fields = "__all__"


class ReceiveOrderLineSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1)
    barcodes = serializers.ListField(child=serializers.CharField(), allow_empty=False)
    branch_id = serializers.UUIDField(required=False)
    location_id = serializers.UUIDField(required=False)


class CancelOrderLineSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1)
