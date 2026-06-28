from django.contrib import admin

from .models import AuditLog, DataQualityIssue, DataQualityRun


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "entity_type", "entity_id", "actor")
    search_fields = ("action", "entity_id", "actor__username")
    list_filter = ("action", "entity_type")
    readonly_fields = ("created_at",)


@admin.register(DataQualityRun)
class DataQualityRunAdmin(admin.ModelAdmin):
    list_display = ("started_at", "status", "started_by", "issue_count")
    list_filter = ("status",)
    readonly_fields = ("started_at", "completed_at")


@admin.register(DataQualityIssue)
class DataQualityIssueAdmin(admin.ModelAdmin):
    list_display = ("code", "severity", "entity_label", "run")
    search_fields = ("code", "message", "entity_label", "entity_id")
    list_filter = ("severity", "code")
