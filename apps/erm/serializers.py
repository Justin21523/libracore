from rest_framework import serializers

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
from .services import proxied_url, resource_coverage_statements


class PlatformSerializer(serializers.ModelSerializer):
    class Meta:
        model = Platform
        fields = "__all__"


class PackageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Package
        fields = "__all__"


class LicenseTermSerializer(serializers.ModelSerializer):
    class Meta:
        model = LicenseTerm
        fields = "__all__"


class LicenseSerializer(serializers.ModelSerializer):
    license_terms = LicenseTermSerializer(many=True, read_only=True)

    class Meta:
        model = License
        fields = "__all__"


class ProxyConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProxyConfig
        fields = "__all__"


class CoverageSerializer(serializers.ModelSerializer):
    statement = serializers.SerializerMethodField()

    class Meta:
        model = Coverage
        fields = "__all__"

    def get_statement(self, obj):
        from .services import coverage_statement

        return coverage_statement(obj)


class AccessUrlSerializer(serializers.ModelSerializer):
    proxied_url = serializers.SerializerMethodField()

    class Meta:
        model = AccessUrl
        fields = "__all__"

    def get_proxied_url(self, obj):
        return proxied_url(obj)


class ElectronicResourceSerializer(serializers.ModelSerializer):
    primary_access_url = serializers.SerializerMethodField()
    coverage_statements = serializers.SerializerMethodField()

    class Meta:
        model = ElectronicResource
        fields = "__all__"

    def get_primary_access_url(self, obj):
        access_url = obj.access_urls.filter(is_primary=True).first() or obj.access_urls.first()
        if access_url:
            return {"label": access_url.label, "url": proxied_url(access_url)}
        if obj.access_url:
            return {"label": "Online access", "url": obj.access_url}
        return None

    def get_coverage_statements(self, obj):
        return resource_coverage_statements(obj)
