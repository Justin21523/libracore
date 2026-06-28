import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.models import BibliographicRecord, Instance, Work
from apps.circulation.models import Loan, Patron
from apps.core.models import AuditLog, DataQualityIssue, DataQualityRun
from apps.core.retention import apply_retention_policy
from apps.core.roles import (
    ROLE_ADMIN,
    ROLE_CATALOGER,
    ROLE_CIRCULATION,
    seed_role_groups,
)
from apps.erm.models import ElectronicResource
from apps.holdings.models import Branch, Holding, Item, Location
from apps.interop.models import ExportJob


def role_user(username: str, role: str):
    seed_role_groups()
    user = get_user_model().objects.create_user(username=username, password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=role))
    return user


@pytest.fixture
def governance_catalog():
    work = Work.objects.create(primary_title="治理測試", language_hint="chi")
    instance = Instance.objects.create(
        work=work,
        title_statement="治理測試",
        publisher="治理出版社",
        publication_date="2026",
        identifiers=[{"scheme": "isbn", "value": "9780000000777"}],
    )
    bib = BibliographicRecord.objects.create(
        source="gov",
        control_number="GOV-001",
        status=BibliographicRecord.Status.APPROVED,
        work=work,
        instance=instance,
    )
    branch = Branch.objects.create(code="gov", name="治理館")
    location = Location.objects.create(branch=branch, code="stack", name="書庫")
    holding = Holding.objects.create(instance=instance, branch=branch, location=location)
    item = Item.objects.create(holding=holding, barcode="GOV-I001", status=Item.Status.AVAILABLE)
    return {
        "work": work,
        "instance": instance,
        "bib": bib,
        "branch": branch,
        "location": location,
        "item": item,
    }


@pytest.mark.django_db
def test_role_permissions_gate_staff_workbenches(governance_catalog):
    circ_user = role_user("circ-role", ROLE_CIRCULATION)
    admin_user = role_user("admin-role", ROLE_ADMIN)
    client = Client()

    client.force_login(circ_user)
    assert client.get(reverse("staff:circulation_desk")).status_code == 200
    assert client.get(reverse("staff:audit_log_list")).status_code == 403

    client.force_login(admin_user)
    assert client.get(reverse("staff:audit_log_list")).status_code == 200


@pytest.mark.django_db
def test_api_create_writes_audit_and_audit_workbench_exports_csv():
    cataloger = role_user("cataloger-role", ROLE_CATALOGER)
    admin_user = role_user("audit-admin", ROLE_ADMIN)
    api = APIClient()
    api.force_authenticate(cataloger)

    created = api.post("/api/works/", {"primary_title": "Audit API Work"}, format="json")
    assert created.status_code == 201
    assert AuditLog.objects.filter(action="work_created", actor=cataloger).exists()

    client = Client()
    client.force_login(admin_user)
    list_response = client.get(reverse("staff:audit_log_list"), {"action": "work_created"})
    export_response = client.get(reverse("staff:audit_log_export"), {"action": "work_created"})

    assert "work_created" in list_response.content.decode()
    assert export_response.status_code == 200
    assert "work_created" in export_response.content.decode()


@pytest.mark.django_db
def test_data_quality_run_finds_catalog_and_erm_issues(governance_catalog):
    admin_user = role_user("dq-admin", ROLE_ADMIN)
    bad_instance = Instance.objects.create(
        title_statement="",
        publisher="",
        publication_date="",
        responsibility_statement="No authority linked",
    )
    BibliographicRecord.objects.create(
        source="dq",
        control_number="DQ-001",
        status=BibliographicRecord.Status.APPROVED,
        instance=bad_instance,
    )
    ElectronicResource.objects.create(
        title="Broken ERM",
        resource_kind=ElectronicResource.ResourceKind.DATABASE,
        status=ElectronicResource.Status.ACTIVE,
        is_public=True,
    )
    client = Client()
    client.force_login(admin_user)

    response = client.post(reverse("staff:data_quality_run"))
    run = DataQualityRun.objects.first()
    codes = set(DataQualityIssue.objects.values_list("code", flat=True))

    assert response.status_code == 302
    assert run.status == DataQualityRun.Status.COMPLETED
    assert "catalog.missing_work_link" in codes
    assert "catalog.missing_isbn_issn" in codes
    assert "erm.missing_access_url" in codes


@pytest.mark.django_db
def test_export_job_staff_ui_creates_export(governance_catalog):
    admin_user = role_user("export-admin", ROLE_ADMIN)
    client = Client()
    client.force_login(admin_user)

    response = client.post(
        reverse("staff:export_job_list"),
        {"export_type": ExportJob.ExportType.DUBLIN_CORE},
    )
    job = ExportJob.objects.get(export_type=ExportJob.ExportType.DUBLIN_CORE)

    assert response.status_code == 302
    assert job.status == ExportJob.Status.COMPLETED
    assert job.record_count == 1


@pytest.mark.django_db
def test_retention_policy_dry_run_and_apply_anonymizes_only_opt_out(governance_catalog):
    branch = governance_catalog["branch"]
    user = get_user_model().objects.create_user(username="retain-reader")
    private_user = get_user_model().objects.create_user(username="retain-private")
    patron = Patron.objects.create(user=user, barcode="RET-1", home_branch=branch)
    private_patron = Patron.objects.create(
        user=private_user,
        barcode="RET-2",
        home_branch=branch,
        privacy_opt_in=True,
    )
    old_date = timezone.now() - timezone.timedelta(days=400)
    Loan.objects.create(
        item=governance_catalog["item"],
        patron=patron,
        due_at=old_date,
        returned_at=old_date,
        status=Loan.Status.RETURNED,
    )
    second_item = Item.objects.create(
        holding=governance_catalog["item"].holding,
        barcode="GOV-I002",
        status=Item.Status.AVAILABLE,
    )
    private_loan = Loan.objects.create(
        item=second_item,
        patron=private_patron,
        due_at=old_date,
        returned_at=old_date,
        status=Loan.Status.RETURNED,
    )

    dry_run = apply_retention_policy(apply=False)
    applied = apply_retention_policy(apply=True)
    private_loan.refresh_from_db()

    assert dry_run.loans_anonymized == 1
    assert applied.loans_anonymized == 1
    assert Loan.objects.filter(anonymized_at__isnull=False).count() == 1
    assert private_loan.patron == private_patron


@pytest.mark.django_db
def test_patron_api_self_scope_limits_loan_visibility(governance_catalog):
    seed_role_groups()
    branch = governance_catalog["branch"]
    first_user = get_user_model().objects.create_user(username="self-reader")
    second_user = get_user_model().objects.create_user(username="other-reader")
    first_patron = Patron.objects.create(user=first_user, barcode="SELF-1", home_branch=branch)
    second_patron = Patron.objects.create(user=second_user, barcode="SELF-2", home_branch=branch)
    Loan.objects.create(
        item=governance_catalog["item"],
        patron=first_patron,
        due_at=timezone.now(),
    )
    second_item = Item.objects.create(
        holding=governance_catalog["item"].holding,
        barcode="SELF-I002",
        status=Item.Status.AVAILABLE,
    )
    Loan.objects.create(item=second_item, patron=second_patron, due_at=timezone.now())
    client = APIClient()
    client.force_authenticate(first_user)

    response = client.get("/api/loans/")
    payload = response.data["results"] if "results" in response.data else response.data

    assert response.status_code == 200
    assert len(payload) == 1
    assert str(payload[0]["patron"]) == str(first_patron.id)
