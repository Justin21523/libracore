import pytest

from apps.catalog.models import BibliographicRecord, Instance, Work
from apps.discovery.indexing import rebuild_all_indexes, rebuild_instance_index
from apps.discovery.models import SearchDocument
from apps.discovery.search import search_documents
from apps.holdings.models import Branch, Holding, Item, Location


@pytest.fixture
def approved_catalog():
    work = Work.objects.create(primary_title="圖書資訊學導論", language_hint="chi")
    instance = Instance.objects.create(
        work=work,
        title_statement="圖書資訊學導論",
        variant_titles=["Library science introduction"],
        publisher="知識出版社",
        publication_date="2024",
        identifiers=[{"scheme": "isbn", "value": "9789570000001"}],
        notes=[{"value": "含參考書目。"}],
    )
    bib = BibliographicRecord.objects.create(
        source="test",
        control_number="bib001",
        status=BibliographicRecord.Status.APPROVED,
        work=work,
        instance=instance,
        metadata={"subjects": [{"label": "圖書資訊學"}]},
    )
    branch = Branch.objects.create(code="main", name="總館")
    location = Location.objects.create(branch=branch, code="stack", name="一般書庫")
    holding = Holding.objects.create(instance=instance, branch=branch, location=location)
    item = Item.objects.create(holding=holding, barcode="D001", status=Item.Status.AVAILABLE)
    return {"work": work, "instance": instance, "bib": bib, "branch": branch, "location": location, "item": item}


@pytest.mark.django_db
def test_rebuild_instance_index_creates_search_document_with_facets(approved_catalog):
    document = rebuild_instance_index(approved_catalog["instance"].id)

    assert document.title_main == "圖書資訊學導論"
    assert document.availability == "available"
    assert document.year_sort == 2024
    assert document.facets["branch"] == ["main"]
    assert "圖書資訊學" in document.subject
    assert "9789570000001" in document.identifiers


@pytest.mark.django_db
def test_unapproved_records_are_not_indexed(approved_catalog):
    approved_catalog["bib"].status = BibliographicRecord.Status.REVIEW
    approved_catalog["bib"].save(update_fields=["status"])

    assert rebuild_instance_index(approved_catalog["instance"].id) is None
    assert SearchDocument.objects.count() == 0


@pytest.mark.django_db
def test_availability_reflects_item_statuses(approved_catalog):
    approved_catalog["item"].status = Item.Status.ON_LOAN
    approved_catalog["item"].save(update_fields=["status"])

    document = rebuild_instance_index(approved_catalog["instance"].id)

    assert document.availability == "on_loan"


@pytest.mark.django_db
def test_search_matches_traditional_and_simplified_chinese(approved_catalog):
    rebuild_instance_index(approved_catalog["instance"].id)

    traditional = search_documents(query="圖書資訊")
    simplified = search_documents(query="图书资讯")

    assert traditional.total == 1
    assert simplified.total == 1


@pytest.mark.django_db
def test_rebuild_all_indexes_removes_unapproved_documents(approved_catalog):
    rebuild_instance_index(approved_catalog["instance"].id)
    approved_catalog["bib"].status = BibliographicRecord.Status.SUPPRESSED
    approved_catalog["bib"].save(update_fields=["status"])

    stats = rebuild_all_indexes()

    assert stats.removed == 1
    assert SearchDocument.objects.count() == 0

