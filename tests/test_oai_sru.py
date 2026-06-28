import pytest
from django.test import Client

from apps.catalog.models import BibliographicRecord, Instance, Work
from apps.discovery.indexing import rebuild_instance_index
from apps.holdings.models import Branch, Holding, Item, Location
from apps.repository.models import DigitalObject


@pytest.fixture
def oai_sru_setup():
    work = Work.objects.create(primary_title="公開探索測試", language_hint="chi")
    instance = Instance.objects.create(
        work=work,
        title_statement="公開探索測試",
        publisher="探索出版社",
        publication_date="2026",
        identifiers=[{"scheme": "isbn", "value": "9780000000888"}],
    )
    bib = BibliographicRecord.objects.create(
        source="local",
        control_number="BIB-OAI-001",
        status=BibliographicRecord.Status.APPROVED,
        work=work,
        instance=instance,
        metadata={"subjects": [{"label": "知識組織"}]},
    )
    branch = Branch.objects.create(code="main", name="總館")
    location = Location.objects.create(branch=branch, code="stack", name="一般書庫")
    holding = Holding.objects.create(instance=instance, branch=branch, location=location)
    Item.objects.create(holding=holding, barcode="OAI001", status=Item.Status.AVAILABLE)
    digital_object = DigitalObject.objects.create(
        title="公開典藏測試",
        bibliographic_record=bib,
        status=DigitalObject.Status.PUBLISHED,
        oai_identifier="oai:libracore:repository:test-object",
        dc_metadata={"creator": ["Repository Author"], "type": "Text"},
        rights_statement="Open access",
    )
    rebuild_instance_index(instance.id)
    return {"bib": bib, "instance": instance, "digital_object": digital_object}


@pytest.mark.django_db
def test_oai_identify_and_metadata_formats(oai_sru_setup):
    client = Client()
    identify = client.get("/oai/", {"verb": "Identify"})
    formats = client.get("/oai/", {"verb": "ListMetadataFormats"})

    assert identify.status_code == 200
    assert "<repositoryName>LibraCore</repositoryName>" in identify.content.decode()
    assert "<metadataPrefix>oai_dc</metadataPrefix>" in formats.content.decode()
    assert "<metadataPrefix>marcxml</metadataPrefix>" in formats.content.decode()


@pytest.mark.django_db
def test_oai_list_records_and_get_record(oai_sru_setup):
    client = Client()
    listed = client.get("/oai/", {"verb": "ListRecords", "metadataPrefix": "oai_dc"})
    fetched = client.get(
        "/oai/",
        {
            "verb": "GetRecord",
            "metadataPrefix": "oai_dc",
            "identifier": f"oai:libracore:bib:{oai_sru_setup['bib'].id}",
        },
    )
    missing = client.get(
        "/oai/",
        {
            "verb": "GetRecord",
            "metadataPrefix": "oai_dc",
            "identifier": "oai:libracore:bib:missing",
        },
    )

    listed_content = listed.content.decode()
    assert "公開探索測試" in listed_content
    assert "公開典藏測試" in listed_content
    assert "知識組織" in fetched.content.decode()
    assert 'code="idDoesNotExist"' in missing.content.decode()


@pytest.mark.django_db
def test_oai_list_identifiers_and_sets(oai_sru_setup):
    client = Client()
    identifiers = client.get("/oai/", {"verb": "ListIdentifiers", "metadataPrefix": "oai_dc"})
    sets = client.get("/oai/", {"verb": "ListSets"})

    assert f"oai:libracore:bib:{oai_sru_setup['bib'].id}" in identifiers.content.decode()
    assert "oai:libracore:repository:test-object" in identifiers.content.decode()
    assert "<setSpec>bibliographic</setSpec>" in sets.content.decode()
    assert "<setSpec>repository</setSpec>" in sets.content.decode()


@pytest.mark.django_db
def test_sru_lite_search_returns_indexed_records(oai_sru_setup):
    response = Client().get(
        "/sru/",
        {"query": 'title="公開探索"', "maximumRecords": "5", "recordSchema": "json"},
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["numberOfRecords"] == 1
    assert payload["records"][0]["recordData"]["title"] == "公開探索測試"
