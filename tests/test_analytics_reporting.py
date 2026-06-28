import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.acquisitions.models import AcquisitionOrder, AcquisitionOrderLine, Vendor
from apps.analytics.models import ReportDefinition, ReportRun
from apps.analytics.services import (
    builtin_report_specs,
    run_report,
    seed_builtin_report_definitions,
)
from apps.catalog.models import BibliographicRecord, Instance, Work
from apps.circulation.models import Loan, Patron
from apps.core.roles import (
    ROLE_ADMIN,
    ROLE_CIRCULATION,
    ROLE_ERM,
    seed_role_groups,
)
from apps.erm.models import ElectronicResource, License, Package
from apps.holdings.models import Branch, Holding, Item, Location
from apps.repository.models import DigitalObject, FileAsset
from apps.serials.models import Issue, SerialTitle, Subscription


def role_user(username: str, role: str):
    seed_role_groups()
    user = get_user_model().objects.create_user(username=username, password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=role))
    return user


@pytest.fixture
def analytics_setup():
    work = Work.objects.create(primary_title="報表測試作品")
    instance = Instance.objects.create(work=work, title_statement="報表測試題名")
    bib = BibliographicRecord.objects.create(
        source="analytics",
        control_number="AN-001",
        status=BibliographicRecord.Status.APPROVED,
        work=work,
        instance=instance,
    )
    branch = Branch.objects.create(code="ana", name="報表館")
    location = Location.objects.create(branch=branch, code="stack", name="書庫")
    holding = Holding.objects.create(instance=instance, branch=branch, location=location)
    item = Item.objects.create(holding=holding, barcode="ANA-I001", status=Item.Status.AVAILABLE)
    second_item = Item.objects.create(
        holding=holding, barcode="ANA-I002", status=Item.Status.AVAILABLE
    )
    reader = get_user_model().objects.create_user(username="analytics-reader")
    patron = Patron.objects.create(user=reader, barcode="ANA-P001", home_branch=branch)
    overdue = Loan.objects.create(
        item=item,
        patron=patron,
        due_at=timezone.now() - timezone.timedelta(days=3),
    )
    returned = Loan.objects.create(
        item=second_item,
        patron=patron,
        due_at=timezone.now() + timezone.timedelta(days=7),
        returned_at=timezone.now(),
        status=Loan.Status.RETURNED,
    )
    vendor = Vendor.objects.create(code="ana-vendor", name="Analytics Vendor")
    order = AcquisitionOrder.objects.create(vendor=vendor, order_number="ANA-PO-1")
    AcquisitionOrderLine.objects.create(order=order, title="採購報表題名", quantity=2)
    license_obj = License.objects.create(
        name="Analytics License",
        status=License.Status.ACTIVE,
        ends_at=timezone.localdate() + timezone.timedelta(days=10),
    )
    Package.objects.create(
        name="Analytics Package",
        license=license_obj,
        status=Package.Status.ACTIVE,
        ends_at=timezone.localdate() + timezone.timedelta(days=20),
    )
    ElectronicResource.objects.create(
        title="Trial Database",
        resource_kind=ElectronicResource.ResourceKind.DATABASE,
        status=ElectronicResource.Status.TRIAL,
    )
    serial = SerialTitle.objects.create(instance=instance, title="報表期刊")
    subscription = Subscription.objects.create(
        serial_title=serial,
        branch=branch,
        location=location,
        status=Subscription.Status.ACTIVE,
    )
    Issue.objects.create(
        serial_title=serial,
        subscription=subscription,
        enumeration="v.1:no.1",
        expected_at=timezone.localdate() - timezone.timedelta(days=10),
    )
    obj = DigitalObject.objects.create(
        title="報表數位物件",
        bibliographic_record=bib,
        status=DigitalObject.Status.PUBLISHED,
    )
    FileAsset.objects.create(
        digital_object=obj,
        file=SimpleUploadedFile("analytics.txt", b"analytics"),
        mime_type="text/plain",
        access_level="public",
    )
    return {
        "branch": branch,
        "location": location,
        "holding": holding,
        "item": item,
        "patron": patron,
        "overdue": overdue,
        "returned": returned,
    }


@pytest.mark.django_db
def test_builtin_report_definitions_are_seeded_without_arbitrary_model_specs():
    definitions = seed_builtin_report_definitions()

    assert len(definitions) == len(builtin_report_specs())
    assert ReportDefinition.objects.filter(code="holdings.inventory_summary").exists()
    assert all(definition.query_spec.get("builtin") is True for definition in definitions)
    assert not any("model" in definition.query_spec for definition in definitions)


@pytest.mark.django_db
def test_report_service_runs_inventory_and_creates_csv(analytics_setup):
    staff = role_user("report-staff", ROLE_CIRCULATION)

    report_run = run_report("holdings.inventory_summary", actor=staff)

    assert report_run.status == ReportRun.Status.COMPLETED
    assert report_run.record_count == 1
    assert report_run.csv_file.name.endswith(".csv")
    assert report_run.result_json["summary"]["total_items"] == 2
    assert "報表館" in report_run.csv_file.read().decode("utf-8-sig")


@pytest.mark.django_db
def test_admin_can_run_all_builtin_reports(analytics_setup):
    admin = role_user("report-admin", ROLE_ADMIN)

    runs = [run_report(code, actor=admin) for code in builtin_report_specs()]

    assert {run.status for run in runs} == {ReportRun.Status.COMPLETED}
    assert ReportRun.objects.count() == len(builtin_report_specs())


@pytest.mark.django_db
def test_report_api_enforces_report_roles(analytics_setup):
    circulation = role_user("analytics-circ", ROLE_CIRCULATION)
    erm = role_user("analytics-erm", ROLE_ERM)
    api = APIClient()

    api.force_authenticate(circulation)
    listing = api.get("/api/report-definitions/")
    payload = listing.data["results"] if "results" in listing.data else listing.data
    visible_codes = {row["code"] for row in payload}
    assert "circulation.overdue_loans" in visible_codes
    assert "erm.expiring_resources" not in visible_codes

    erm_definition = ReportDefinition.objects.get(code="erm.expiring_resources")
    denied = api.post(f"/api/report-definitions/{erm_definition.id}/run/", {}, format="json")
    assert denied.status_code == 404

    erm_api = APIClient()
    erm_api.force_authenticate(erm)
    allowed = erm_api.post(
        f"/api/report-definitions/{erm_definition.id}/run/",
        {"days": 30},
        format="json",
    )
    assert allowed.status_code == 201
    assert allowed.data["status"] == ReportRun.Status.COMPLETED


@pytest.mark.django_db
def test_staff_analytics_workbench_runs_and_downloads_report(analytics_setup):
    staff = role_user("analytics-ui", ROLE_CIRCULATION)
    client = Client()
    client.force_login(staff)

    dashboard = client.get(reverse("staff:analytics_dashboard"))
    detail = client.get(
        reverse("staff:analytics_report_detail", args=["circulation.overdue_loans"])
    )
    submitted = client.post(
        reverse("staff:analytics_report_run", args=["circulation.overdue_loans"]),
        {"limit": "25"},
    )
    report_run = ReportRun.objects.get(code="circulation.overdue_loans")
    result = client.get(reverse("staff:analytics_run_detail", args=[report_run.id]))
    download = client.get(reverse("staff:analytics_run_download", args=[report_run.id]))

    assert dashboard.status_code == 200
    assert "逾期借閱清單" in dashboard.content.decode()
    assert detail.status_code == 200
    assert submitted.status_code == 302
    assert "ANA-I001" in result.content.decode()
    assert download.status_code == 200
    assert download["Content-Type"] == "text/csv"


@pytest.mark.django_db
def test_run_report_management_command_creates_report_run(analytics_setup):
    call_command("run_report", code="holdings.inventory_summary")

    report_run = ReportRun.objects.get(code="holdings.inventory_summary")
    assert report_run.status == ReportRun.Status.COMPLETED
    assert report_run.record_count == 1
