import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.catalog.models import BibliographicRecord, Instance, Work
from apps.discovery.indexing import rebuild_instance_index
from apps.holdings.models import Branch, Holding, Item, Location


@pytest.fixture
def indexed_document():
    work = Work.objects.create(primary_title="資料庫系統概論", language_hint="chi")
    instance = Instance.objects.create(
        work=work,
        title_statement="資料庫系統概論",
        publisher="資料出版社",
        publication_date="2023",
        identifiers=[{"scheme": "isbn", "value": "9780000000002"}],
    )
    BibliographicRecord.objects.create(
        source="api",
        control_number="api001",
        status=BibliographicRecord.Status.APPROVED,
        work=work,
        instance=instance,
        metadata={"subjects": [{"label": "資料庫"}]},
    )
    branch = Branch.objects.create(code="main", name="總館")
    location = Location.objects.create(branch=branch, code="stack", name="一般書庫")
    holding = Holding.objects.create(instance=instance, branch=branch, location=location)
    Item.objects.create(holding=holding, barcode="S001", status=Item.Status.AVAILABLE)
    return rebuild_instance_index(instance.id)


@pytest.mark.django_db
def test_search_api_returns_results_and_facets(indexed_document):
    response = APIClient().get("/api/search-documents/search/", {"q": "資料庫"})

    assert response.status_code == 200
    assert response.data["count"] == 1
    assert response.data["results"][0]["title_main"] == "資料庫系統概論"
    assert response.data["facets"]["availability"]["available"] == 1


@pytest.mark.django_db
def test_rebuild_api_is_staff_only(indexed_document):
    client = APIClient()
    response = client.post("/api/search-documents/rebuild/")
    assert response.status_code == 403

    staff = get_user_model().objects.create_user(username="search-staff", password="x", is_staff=True)
    client.force_authenticate(staff)
    response = client.post("/api/search-documents/rebuild/")
    assert response.status_code == 200
    assert response.data["indexed"] >= 1

