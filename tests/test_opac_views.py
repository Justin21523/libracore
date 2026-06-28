import pytest
from django.urls import reverse

from apps.catalog.models import BibliographicRecord, Instance, Work
from apps.discovery.indexing import rebuild_instance_index
from apps.holdings.models import Branch, Holding, Item, Location


@pytest.fixture
def opac_record():
    work = Work.objects.create(primary_title="公共圖書館服務", language_hint="chi")
    instance = Instance.objects.create(
        work=work,
        title_statement="公共圖書館服務",
        publisher="城市出版社",
        publication_date="2022",
    )
    BibliographicRecord.objects.create(
        source="opac",
        control_number="opac001",
        status=BibliographicRecord.Status.APPROVED,
        work=work,
        instance=instance,
        metadata={"subjects": [{"label": "公共圖書館"}]},
    )
    branch = Branch.objects.create(code="city", name="城市館")
    location = Location.objects.create(branch=branch, code="open", name="開架")
    holding = Holding.objects.create(instance=instance, branch=branch, location=location)
    Item.objects.create(holding=holding, barcode="O001", status=Item.Status.AVAILABLE)
    rebuild_instance_index(instance.id)
    return instance


@pytest.mark.django_db
def test_opac_home_search_and_record_detail_render(client, opac_record):
    home = client.get(reverse("discovery:home"))
    assert home.status_code == 200

    results = client.get(reverse("discovery:search"), {"q": "公共圖書館"})
    assert results.status_code == 200
    assert "公共圖書館服務" in results.content.decode()

    detail = client.get(reverse("discovery:record_detail", args=[opac_record.id]))
    assert detail.status_code == 200
    assert "城市出版社" in detail.content.decode()

    availability = client.get(reverse("discovery:record_availability", args=[opac_record.id]))
    assert availability.status_code == 200
    assert "O001" in availability.content.decode()

