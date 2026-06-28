import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.marc.models import MarcImportBatch
from tests.test_marc_parser import sample_bibliographic_record


@pytest.mark.django_db
def test_staff_cataloging_import_views_smoke():
    staff = get_user_model().objects.create_user(username="staff-view", password="x", is_staff=True)
    client = Client()
    client.force_login(staff)

    response = client.get(reverse("staff:import_batch_list"))
    assert response.status_code == 200

    upload = SimpleUploadedFile("sample.mrc", sample_bibliographic_record(), content_type="application/octet-stream")
    response = client.post(
        reverse("staff:import_batch_new"),
        {"source": "view", "import_format": "iso2709", "file": upload},
    )
    assert response.status_code == 302
    batch = MarcImportBatch.objects.get()

    response = client.post(reverse("staff:import_batch_parse", args=[batch.id]))
    assert response.status_code == 302

    record = batch.records.get()
    response = client.get(reverse("staff:import_record_review", args=[record.id]))
    assert response.status_code == 200
    assert "圖書資訊學導論" in response.content.decode()

