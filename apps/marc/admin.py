from django.contrib import admin

from .models import (
    AuthorityLinkSuggestion,
    MarcImportBatch,
    MarcImportRecord,
    MarcMatchCandidate,
    MarcRecord,
)


@admin.register(MarcRecord)
class MarcRecordAdmin(admin.ModelAdmin):
    list_display = ("format_type", "control_number", "source", "validation_status", "imported_at")
    search_fields = ("control_number", "source", "leader")
    list_filter = ("format_type", "validation_status", "source")


class MarcImportRecordInline(admin.TabularInline):
    model = MarcImportRecord
    extra = 0
    fields = ("sequence", "format_type", "status", "control_number", "conflict_reason")
    readonly_fields = ("sequence", "format_type", "status", "control_number", "conflict_reason")


@admin.register(MarcImportBatch)
class MarcImportBatchAdmin(admin.ModelAdmin):
    list_display = ("filename", "source", "import_format", "status", "record_count", "created_at")
    search_fields = ("filename", "source")
    list_filter = ("import_format", "status", "source")
    inlines = [MarcImportRecordInline]


@admin.register(MarcImportRecord)
class MarcImportRecordAdmin(admin.ModelAdmin):
    list_display = (
        "batch",
        "sequence",
        "format_type",
        "status",
        "control_number",
        "resolution_action",
    )
    search_fields = ("control_number", "raw_payload", "conflict_reason")
    list_filter = ("format_type", "status", "resolution_action")


@admin.register(MarcMatchCandidate)
class MarcMatchCandidateAdmin(admin.ModelAdmin):
    list_display = ("import_record", "target_type", "target_id", "match_rule", "confidence")
    search_fields = ("target_id", "match_rule", "reason")
    list_filter = ("target_type", "match_rule", "confidence")


@admin.register(AuthorityLinkSuggestion)
class AuthorityLinkSuggestionAdmin(admin.ModelAdmin):
    list_display = ("label", "marc_tag", "authority_type", "status", "confidence")
    search_fields = ("label", "marc_tag", "authority_type")
    list_filter = ("authority_type", "status", "marc_tag")
