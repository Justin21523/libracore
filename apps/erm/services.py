from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Q
from django.utils import timezone

from .models import AccessUrl, Coverage, ElectronicResource, License, Package, ProxyConfig

PUBLIC_RESOURCE_STATUSES = [ElectronicResource.Status.ACTIVE, ElectronicResource.Status.TRIAL]


@dataclass(frozen=True)
class PublicAccessLink:
    label: str
    url: str
    original_url: str
    requires_proxy: bool = False


def public_resources_for_instance(instance) -> list[ElectronicResource]:
    return list(
        ElectronicResource.objects.filter(
            instance=instance,
            is_active=True,
            is_public=True,
            status__in=PUBLIC_RESOURCE_STATUSES,
        )
        .select_related("platform_ref", "package", "license")
        .prefetch_related("access_urls__proxy_config", "coverages", "license__license_terms")
        .order_by("title")
    )


def primary_access_url(resource: ElectronicResource) -> AccessUrl | None:
    urls = list(resource.access_urls.all())
    primary = [access_url for access_url in urls if access_url.is_primary]
    if primary:
        return primary[0]
    if urls:
        return urls[0]
    if resource.access_url:
        return AccessUrl(
            resource=resource,
            label="Online access",
            url=resource.access_url,
            is_primary=True,
            requires_proxy=False,
        )
    return None


def public_access_links(resource: ElectronicResource) -> list[PublicAccessLink]:
    urls = list(resource.access_urls.all())
    if not urls and resource.access_url:
        urls = [
            AccessUrl(
                resource=resource,
                label="Online access",
                url=resource.access_url,
                is_primary=True,
                requires_proxy=False,
            )
        ]
    return [
        PublicAccessLink(
            label=access_url.label,
            url=proxied_url(access_url),
            original_url=access_url.url,
            requires_proxy=access_url.requires_proxy,
        )
        for access_url in urls
    ]


def proxied_url(access_url: AccessUrl) -> str:
    if not access_url.requires_proxy:
        return access_url.url
    proxy = access_url.proxy_config or default_proxy_config()
    if not proxy or not proxy.is_active:
        return access_url.url
    return f"{proxy.proxy_prefix}{access_url.url}"


def default_proxy_config() -> ProxyConfig | None:
    return (
        ProxyConfig.objects.filter(is_active=True, is_default=True).first()
        or ProxyConfig.objects.filter(is_active=True).first()
    )


def coverage_statement(coverage: Coverage) -> str:
    start = coverage.start_date.isoformat() if coverage.start_date else "unknown"
    end = coverage.end_date.isoformat() if coverage.end_date else "present"
    label = f"Available from {start} to {end}"
    if coverage.embargo:
        label = f"{label}; embargo: {coverage.embargo}"
    if coverage.coverage_note:
        label = f"{label}; {coverage.coverage_note}"
    return label


def resource_coverage_statements(resource: ElectronicResource) -> list[str]:
    structured = [coverage_statement(coverage) for coverage in resource.coverages.all()]
    if structured:
        return structured
    legacy = resource.coverage or {}
    if isinstance(legacy, dict) and (legacy.get("start") or legacy.get("end")):
        return [
            f"Available from {legacy.get('start', 'unknown')} to {legacy.get('end', 'present')}"
        ]
    return []


def license_expiry_queryset(today=None):
    today = today or timezone.localdate()
    return (
        License.objects.exclude(ends_at__isnull=True)
        .filter(status=License.Status.ACTIVE)
        .filter(ends_at__lte=today + timezone.timedelta(days=365))
        .select_related("vendor", "invoice")
        .order_by("ends_at")
    )


def licenses_due_for_notice(today=None) -> list[License]:
    today = today or timezone.localdate()
    licenses = license_expiry_queryset(today)
    return [
        license
        for license in licenses
        if license.ends_at <= today + timezone.timedelta(days=license.renewal_notice_days)
    ]


def package_expiry_queryset(today=None):
    today = today or timezone.localdate()
    return (
        Package.objects.exclude(ends_at__isnull=True)
        .filter(Q(status=Package.Status.ACTIVE) | Q(status=Package.Status.TRIAL))
        .filter(ends_at__lte=today + timezone.timedelta(days=365))
        .select_related("platform", "vendor", "license")
        .order_by("ends_at")
    )


def erm_index_values(instance) -> tuple[str, dict]:
    resources = public_resources_for_instance(instance)
    if not resources:
        return "", {
            "online_available": ["false"],
            "platform": [],
            "platform_name": [],
            "resource_mode": [],
        }
    text_parts: list[str] = []
    platform_codes: set[str] = set()
    platform_names: set[str] = set()
    modes: set[str] = set()
    for resource in resources:
        links = public_access_links(resource)
        coverage = resource_coverage_statements(resource)
        platform_name = (
            resource.platform_ref.name if resource.platform_ref_id else resource.platform
        )
        platform_code = (
            resource.platform_ref.code if resource.platform_ref_id else resource.platform
        )
        if platform_code:
            platform_codes.add(platform_code)
        if platform_name:
            platform_names.add(platform_name)
        modes.add(resource.resource_mode)
        text_parts.extend(
            [
                resource.title,
                resource.resource_kind,
                resource.resource_mode,
                platform_name,
                " ".join(link.label for link in links),
                " ".join(link.original_url for link in links),
                " ".join(coverage),
            ]
        )
    return (
        " ".join(part for part in text_parts if part),
        {
            "online_available": ["true"],
            "platform": sorted(platform_codes),
            "platform_name": sorted(platform_names),
            "resource_mode": sorted(modes),
        },
    )
