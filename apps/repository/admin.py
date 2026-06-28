from django.contrib import admin

from .models import DigitalObject, FileAsset

admin.site.register(DigitalObject)
admin.site.register(FileAsset)
