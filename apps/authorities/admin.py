from django.contrib import admin

from .models import AccessPoint, AuthorityRecord, AuthorityRelation, ExternalIdentifier


class AccessPointInline(admin.TabularInline):
    model = AccessPoint
    extra = 0


@admin.register(AuthorityRecord)
class AuthorityRecordAdmin(admin.ModelAdmin):
    list_display = ("authority_type", "status", "source", "control_number", "entity_uri", "deprecated_replacement")
    search_fields = ("control_number", "entity_uri", "access_points__label")
    list_filter = ("authority_type", "status", "source")
    inlines = [AccessPointInline]


admin.site.register(AuthorityRelation)
admin.site.register(ExternalIdentifier)
