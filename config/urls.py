from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.acquisitions.api import register as register_acquisitions
from apps.analytics.api import register as register_analytics
from apps.authorities.api import register as register_authorities
from apps.catalog.api import register as register_catalog
from apps.circulation.api import register as register_circulation
from apps.core.api import register as register_core
from apps.discovery.api import register as register_discovery
from apps.erm.api import register as register_erm
from apps.holdings.api import register as register_holdings
from apps.interop.api import register as register_interop
from apps.marc.api import register as register_marc
from apps.notifications.api import register as register_notifications
from apps.repository.api import register as register_repository
from apps.serials.api import register as register_serials
from apps.vocabularies.api import register as register_vocabularies

router = DefaultRouter()
for registrar in [
    register_authorities,
    register_core,
    register_vocabularies,
    register_catalog,
    register_marc,
    register_holdings,
    register_circulation,
    register_acquisitions,
    register_serials,
    register_erm,
    register_notifications,
    register_repository,
    register_interop,
    register_discovery,
    register_analytics,
]:
    registrar(router)

urlpatterns = [
    path("", include("apps.discovery.urls")),
    path("", include("apps.authorities.urls")),
    path("", include("apps.interop.urls")),
    path("", include("apps.repository.urls")),
    path("accounts/", include("django.contrib.auth.urls")),
    path("admin/", admin.site.urls),
    path("staff/", include("apps.staff.urls")),
    path("api/", include(router.urls)),
    path("api-auth/", include("rest_framework.urls")),
]
