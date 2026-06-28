from django.contrib import admin

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

admin.site.register(Vendor)
admin.site.register(Fund)
admin.site.register(FundTransaction)
admin.site.register(PurchaseRequest)
admin.site.register(AcquisitionOrder)
admin.site.register(AcquisitionOrderLine)
admin.site.register(ReceivingEvent)
admin.site.register(Invoice)
admin.site.register(InvoiceLine)
