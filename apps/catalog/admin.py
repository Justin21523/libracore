from django.contrib import admin

from .models import BibliographicRecord, Expression, Instance, InstanceContributor, Work, WorkAuthorityLink


@admin.register(Work)
class WorkAdmin(admin.ModelAdmin):
    list_display = ("primary_title", "date", "language_hint", "updated_at")
    search_fields = ("primary_title", "original_title", "summary")


@admin.register(Instance)
class InstanceAdmin(admin.ModelAdmin):
    list_display = ("title_statement", "resource_type", "publisher", "publication_date")
    search_fields = ("title_statement", "responsibility_statement", "publisher")
    list_filter = ("resource_type",)


admin.site.register(Expression)
admin.site.register(BibliographicRecord)
admin.site.register(WorkAuthorityLink)
admin.site.register(InstanceContributor)

