from django.contrib import admin

from .models import (
    BoundVolume,
    ClaimEvent,
    Issue,
    IssuePredictionPattern,
    SerialCheckInEvent,
    SerialTitle,
    Subscription,
)

admin.site.register(SerialTitle)
admin.site.register(Subscription)
admin.site.register(IssuePredictionPattern)
admin.site.register(Issue)
admin.site.register(SerialCheckInEvent)
admin.site.register(ClaimEvent)
admin.site.register(BoundVolume)
