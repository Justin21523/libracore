from django.contrib import admin

from .models import (
    AccessUrl,
    Coverage,
    ElectronicResource,
    License,
    LicenseTerm,
    Package,
    Platform,
    ProxyConfig,
)

admin.site.register(AccessUrl)
admin.site.register(Coverage)
admin.site.register(ElectronicResource)
admin.site.register(License)
admin.site.register(LicenseTerm)
admin.site.register(Package)
admin.site.register(Platform)
admin.site.register(ProxyConfig)
