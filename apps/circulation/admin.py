from django.contrib import admin

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


admin.site.register(CirculationPolicy)
admin.site.register(BranchCalendarException)
admin.site.register(Patron)
admin.site.register(Loan)
admin.site.register(HoldRequest)
admin.site.register(FineFee)
admin.site.register(Payment)
admin.site.register(PaymentAllocation)
admin.site.register(FeeWaiver)
