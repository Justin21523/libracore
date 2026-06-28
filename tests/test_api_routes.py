import pytest
from rest_framework.test import APIClient

from apps.catalog.models import Work


@pytest.mark.django_db
def test_work_api_lists_catalog_records():
    Work.objects.create(primary_title="資料庫系統概論")

    response = APIClient().get("/api/works/")

    assert response.status_code == 200
    assert response.data["results"][0]["primary_title"] == "資料庫系統概論" if "results" in response.data else response.data[0]["primary_title"] == "資料庫系統概論"

