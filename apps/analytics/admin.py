from django.contrib import admin

from .models import ReportDefinition, ReportRun

admin.site.register(ReportDefinition)
admin.site.register(ReportRun)
