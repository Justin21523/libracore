import pytest
from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from rest_framework.test import APIClient

from apps.catalog.models import BibliographicRecord, Instance, Work
from apps.circulation.models import FineFee, Patron
from apps.holdings.models import Branch, Holding, Item, Location
from apps.interop.models import ExportJob
from apps.marc.models import MarcRecord


@pytest.fixture
def interop_catalog_setup():
    work = Work.objects.create(primary_title="互通測試", language_hint="chi")
    instance = Instance.objects.create(
        work=work,
        title_statement="互通測試",
        publisher="開放出版社",
        publication_date="2026",
        identifiers=[{"scheme": "isbn", "value": "9780000000999"}],
    )
    bib = BibliographicRecord.objects.create(
        source="local",
        control_number="BIB-EXPORT-001",
        status=BibliographicRecord.Status.APPROVED,
        work=work,
        instance=instance,
        metadata={"subjects": [{"label": "資訊組織"}]},
    )
    MarcRecord.objects.create(
        bibliographic_record=bib,
        format_type=MarcRecord.FormatType.BIBLIOGRAPHIC,
        control_number="BIB-EXPORT-001",
        parsed_json={
            "leader": "00000nam a2200000 a 4500",
            "fields": [
                {"tag": "001", "value": "BIB-EXPORT-001"},
                {
                    "tag": "245",
                    "indicators": ["0", "0"],
                    "subfields": [{"code": "a", "value": "互通測試"}],
                },
            ],
        },
    )
    branch = Branch.objects.create(code="main", name="總館")
    location = Location.objects.create(branch=branch, code="stack", name="一般書庫")
    holding = Holding.objects.create(instance=instance, branch=branch, location=location)
    Item.objects.create(holding=holding, barcode="EXP001", status=Item.Status.AVAILABLE)
    user = get_user_model().objects.create_user(
        username="export-reader", email="reader@example.test"
    )
    patron = Patron.objects.create(user=user, barcode="P-EXPORT", home_branch=branch)
    FineFee.objects.create(
        patron=patron,
        reason="Manual test fee",
        amount="20.00",
        original_amount="20.00",
        balance_amount="20.00",
    )
    return {"bib": bib, "instance": instance, "patron": patron}


@pytest.fixture
def staff_client():
    staff = get_user_model().objects.create_user(
        username="interop-staff",
        password="x",
        is_staff=True,
    )
    client = APIClient()
    client.force_authenticate(staff)
    return client


@pytest.mark.django_db
def test_export_job_api_creates_marcxml_file(staff_client, interop_catalog_setup):
    response = staff_client.post(
        "/api/export-jobs/",
        {"export_type": ExportJob.ExportType.MARCXML_BIB},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["status"] == ExportJob.Status.COMPLETED
    assert response.data["record_count"] == 1

    job = ExportJob.objects.get(id=response.data["id"])
    content = default_storage.open(job.result_file.name).read().decode()
    assert "<marc:collection" in content
    assert "互通測試" in content


@pytest.mark.django_db
def test_export_job_api_creates_dublin_core_file(staff_client, interop_catalog_setup):
    response = staff_client.post(
        "/api/export-jobs/",
        {"export_type": ExportJob.ExportType.DUBLIN_CORE},
        format="json",
    )

    assert response.status_code == 201
    job = ExportJob.objects.get(id=response.data["id"])
    content = default_storage.open(job.result_file.name).read().decode()
    assert "<dc:title>互通測試</dc:title>" in content
    assert "<dc:identifier>BIB-EXPORT-001</dc:identifier>" in content


@pytest.mark.django_db
def test_export_job_api_creates_csv_file(staff_client, interop_catalog_setup):
    response = staff_client.post(
        "/api/export-jobs/",
        {"export_type": ExportJob.ExportType.CSV_PATRONS},
        format="json",
    )

    assert response.status_code == 201
    job = ExportJob.objects.get(id=response.data["id"])
    content = default_storage.open(job.result_file.name).read().decode()
    assert "barcode,username,email,patron_type,expiry_date,home_branch" in content
    assert "P-EXPORT,export-reader,reader@example.test,standard,,總館" in content


@pytest.mark.django_db
def test_export_job_api_is_staff_only(interop_catalog_setup):
    response = APIClient().post(
        "/api/export-jobs/",
        {"export_type": ExportJob.ExportType.MARCXML_BIB},
        format="json",
    )

    assert response.status_code == 403
