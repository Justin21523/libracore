from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.acquisitions.models import Vendor
from apps.catalog.models import BibliographicRecord, Instance, Work
from apps.discovery.indexing import rebuild_instance_index
from apps.discovery.search import search_documents
from apps.erm.models import (
    AccessUrl,
    Coverage,
    ElectronicResource,
    License,
    LicenseTerm,
    Package,
    Platform,
    ProxyConfig,
)
from apps.erm.services import licenses_due_for_notice, public_access_links


@pytest.fixture
def erm_setup():
    vendor = Vendor.objects.create(code="erm-vendor", name="ERM Vendor")
    work = Work.objects.create(primary_title="電子期刊測試")
    instance = Instance.objects.create(
        work=work,
        resource_type=Instance.ResourceType.SERIAL,
        title_statement="電子期刊測試",
        identifiers=[{"scheme": "issn", "value": "2468-1357"}],
    )
    BibliographicRecord.objects.create(
        source="erm",
        control_number="ERM-001",
        status=BibliographicRecord.Status.APPROVED,
        work=work,
        instance=instance,
    )
    platform = Platform.objects.create(
        code="jstor-test",
        name="JSTOR Test",
        vendor=vendor,
        base_url="https://jstor.example/",
    )
    license_obj = License.objects.create(
        name="JSTOR 2026 License",
        vendor=vendor,
        status=License.Status.ACTIVE,
        starts_at=date(2026, 1, 1),
        ends_at=timezone.localdate() + timezone.timedelta(days=30),
        renewal_notice_days=60,
    )
    LicenseTerm.objects.create(
        license=license_obj,
        term_type=LicenseTerm.TermType.REMOTE_ACCESS,
        allowed=True,
    )
    package = Package.objects.create(
        name="JSTOR Arts Package",
        platform=platform,
        vendor=vendor,
        license=license_obj,
        status=Package.Status.ACTIVE,
        ends_at=timezone.localdate() + timezone.timedelta(days=90),
    )
    resource = ElectronicResource.objects.create(
        instance=instance,
        title="電子期刊測試 Online",
        resource_kind=ElectronicResource.ResourceKind.EJOURNAL,
        status=ElectronicResource.Status.ACTIVE,
        resource_mode=ElectronicResource.ResourceMode.ONLINE,
        platform_ref=platform,
        package=package,
        license=license_obj,
        is_public=True,
    )
    proxy = ProxyConfig.objects.create(
        code="ezproxy",
        name="EZproxy",
        proxy_prefix="https://proxy.example/login?url=",
        is_default=True,
    )
    AccessUrl.objects.create(
        resource=resource,
        label="Full text",
        url="https://jstor.example/journal/test",
        is_primary=True,
        requires_proxy=True,
        proxy_config=proxy,
    )
    Coverage.objects.create(
        resource=resource,
        coverage_type=Coverage.CoverageType.FULL_TEXT,
        start_date=date(2010, 1, 1),
        end_date=None,
    )
    return {
        "vendor": vendor,
        "instance": instance,
        "platform": platform,
        "license": license_obj,
        "package": package,
        "resource": resource,
    }


@pytest.mark.django_db
def test_erm_public_access_links_and_license_notice(erm_setup):
    links = public_access_links(erm_setup["resource"])
    due = licenses_due_for_notice()

    assert links[0].url == "https://proxy.example/login?url=https://jstor.example/journal/test"
    assert links[0].requires_proxy is True
    assert erm_setup["license"] in due


@pytest.mark.django_db
def test_erm_api_staff_write_and_public_read(erm_setup):
    client = APIClient()

    read_response = client.get("/api/electronic-resources/")
    assert read_response.status_code == 200

    denied = client.post("/api/platforms/", {"code": "denied", "name": "Denied"}, format="json")
    assert denied.status_code == 403

    staff = get_user_model().objects.create_user(username="erm-api", password="x", is_staff=True)
    client.force_authenticate(staff)
    created = client.post(
        "/api/platforms/",
        {"code": "created-platform", "name": "Created Platform"},
        format="json",
    )
    assert created.status_code == 201


@pytest.mark.django_db
def test_discovery_indexes_erm_online_facets_and_search(erm_setup):
    document = rebuild_instance_index(erm_setup["instance"].id)
    results = search_documents(query="JSTOR Test", filters={"online_available": "true"})

    assert document.facets["online_available"] == ["true"]
    assert document.facets["platform_name"] == ["JSTOR Test"]
    assert document.facets["resource_mode"] == [ElectronicResource.ResourceMode.ONLINE]
    assert results.total == 1


@pytest.mark.django_db
def test_opac_record_detail_displays_online_resource_and_coverage(erm_setup):
    rebuild_instance_index(erm_setup["instance"].id)

    response = Client().get(reverse("discovery:record_detail", args=[erm_setup["instance"].id]))
    content = response.content.decode()

    assert response.status_code == 200
    assert "線上資源" in content
    assert "JSTOR Test" in content
    assert "Available from 2010-01-01 to present" in content
    assert "https://proxy.example/login?url=https://jstor.example/journal/test" in content


@pytest.mark.django_db
def test_staff_erm_views_render(erm_setup):
    staff = get_user_model().objects.create_user(username="erm-view", password="x", is_staff=True)
    client = Client()
    client.force_login(staff)

    pages = [
        reverse("staff:erm_resource_list"),
        reverse("staff:erm_resource_detail", args=[erm_setup["resource"].id]),
        reverse("staff:erm_license_list"),
        reverse("staff:erm_license_detail", args=[erm_setup["license"].id]),
        reverse("staff:erm_platform_list"),
        reverse("staff:erm_package_list"),
        reverse("staff:erm_expiry_list"),
    ]
    for url in pages:
        response = client.get(url)
        assert response.status_code == 200
        assert "JSTOR" in response.content.decode() or "ERM" in response.content.decode()
