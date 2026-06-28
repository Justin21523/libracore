from rest_framework import permissions

from apps.core.api import BaseModelViewSet
from apps.core.roles import ROLE_ERM, user_has_role

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
from .serializers import (
    AccessUrlSerializer,
    CoverageSerializer,
    ElectronicResourceSerializer,
    LicenseSerializer,
    LicenseTermSerializer,
    PackageSerializer,
    PlatformSerializer,
    ProxyConfigSerializer,
)


class StaffWritePermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return user_has_role(request.user, ROLE_ERM)


class PlatformViewSet(BaseModelViewSet):
    queryset = Platform.objects.select_related("vendor").all()
    serializer_class = PlatformSerializer
    permission_classes = [StaffWritePermission]
    search_fields = ["code", "name", "base_url", "notes"]


class PackageViewSet(BaseModelViewSet):
    queryset = Package.objects.select_related("platform", "vendor", "license").all()
    serializer_class = PackageSerializer
    permission_classes = [StaffWritePermission]
    search_fields = ["name", "platform__name", "vendor__name", "notes"]


class LicenseViewSet(BaseModelViewSet):
    queryset = (
        License.objects.select_related("vendor", "invoice").prefetch_related("license_terms").all()
    )
    serializer_class = LicenseSerializer
    permission_classes = [StaffWritePermission]
    search_fields = ["name", "licensor", "vendor__name", "notes"]


class LicenseTermViewSet(BaseModelViewSet):
    queryset = LicenseTerm.objects.select_related("license").all()
    serializer_class = LicenseTermSerializer
    permission_classes = [StaffWritePermission]
    search_fields = ["license__name", "term_type", "note"]


class ProxyConfigViewSet(BaseModelViewSet):
    queryset = ProxyConfig.objects.all()
    serializer_class = ProxyConfigSerializer
    permission_classes = [StaffWritePermission]
    search_fields = ["code", "name", "proxy_prefix", "notes"]


class ElectronicResourceViewSet(BaseModelViewSet):
    queryset = (
        ElectronicResource.objects.select_related("instance", "platform_ref", "package", "license")
        .prefetch_related("access_urls", "coverages")
        .all()
    )
    serializer_class = ElectronicResourceSerializer
    permission_classes = [StaffWritePermission]
    search_fields = [
        "title",
        "platform",
        "platform_ref__name",
        "access_url",
        "identifiers",
    ]


class CoverageViewSet(BaseModelViewSet):
    queryset = Coverage.objects.select_related("resource").all()
    serializer_class = CoverageSerializer
    permission_classes = [StaffWritePermission]
    search_fields = ["resource__title", "coverage_note", "embargo"]


class AccessUrlViewSet(BaseModelViewSet):
    queryset = AccessUrl.objects.select_related("resource", "proxy_config").all()
    serializer_class = AccessUrlSerializer
    permission_classes = [StaffWritePermission]
    search_fields = ["resource__title", "label", "url", "notes"]


def register(router):
    router.register("platforms", PlatformViewSet, basename="platform")
    router.register("packages", PackageViewSet, basename="package")
    router.register("licenses", LicenseViewSet, basename="license")
    router.register("license-terms", LicenseTermViewSet, basename="license-term")
    router.register("proxy-configs", ProxyConfigViewSet, basename="proxy-config")
    router.register(
        "electronic-resources", ElectronicResourceViewSet, basename="electronic-resource"
    )
    router.register("coverages", CoverageViewSet, basename="coverage")
    router.register("access-urls", AccessUrlViewSet, basename="access-url")
