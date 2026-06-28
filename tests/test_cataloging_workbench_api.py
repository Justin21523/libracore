import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.catalog.models import BibliographicRecord
from apps.marc.models import MarcImportBatch, MarcImportRecord
from tests.test_marc_parser import sample_bibliographic_record


@pytest.mark.django_db
def test_staff_can_create_parse_and_approve_import_record_via_api():
    staff = get_user_model().objects.create_user(username="cataloger", password="x", is_staff=True)
    client = APIClient()
    client.force_authenticate(staff)

    created = client.post(
        "/api/marc-import-batches/",
        {
            "source": "api",
            "import_format": "iso2709",
            "filename": "api.mrc",
            "payload": sample_bibliographic_record().decode("utf-8", errors="replace"),
        },
        format="json",
    )
    assert created.status_code == 201

    parsed = client.post(f"/api/marc-import-batches/{created.data['id']}/parse/")
    assert parsed.status_code == 200
    record = MarcImportRecord.objects.get(batch_id=created.data["id"])
    assert record.status == MarcImportRecord.Status.PARSED

    approved = client.post(f"/api/marc-import-records/{record.id}/approve/", {}, format="json")
    assert approved.status_code == 200
    assert BibliographicRecord.objects.count() == 1


@pytest.mark.django_db
def test_non_staff_cannot_create_import_batch_via_api():
    user = get_user_model().objects.create_user(username="reader", password="x")
    client = APIClient()
    client.force_authenticate(user)

    response = client.post(
        "/api/marc-import-batches/",
        {"source": "api", "import_format": "json", "payload": "{}"},
        format="json",
    )

    assert response.status_code == 403

