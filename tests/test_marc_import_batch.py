import json

import pytest

from apps.authorities.models import AccessPoint, AuthorityRecord
from apps.catalog.models import BibliographicRecord, Instance, WorkAuthorityLink
from apps.marc.importers import parse_json_marc_records, parse_marcxml_records
from apps.marc.models import AuthorityLinkSuggestion, MarcImportBatch, MarcImportRecord
from apps.marc.review_services import (
    accept_authority_suggestion,
    approve_import_record,
    create_import_batch,
    create_provisional_authority_from_suggestion,
    parse_import_batch,
)
from tests.test_marc_parser import sample_bibliographic_record


def sample_json_marc_payload():
    return json.dumps(
        {
            "leader": "00000nam a2200000 i 4500",
            "fields": [
                {"tag": "001", "value": "json001"},
                {"tag": "008", "value": "240101s2024    ch            000 0 chi  "},
                {"tag": "245", "indicators": ["1", "0"], "subfields": [{"code": "a", "value": "JSON 編目 :"}]},
            ],
        },
        ensure_ascii=False,
    )


def sample_marcxml_payload():
    return """<collection xmlns="http://www.loc.gov/MARC21/slim">
      <record>
        <leader>00000nam a2200000 i 4500</leader>
        <controlfield tag="001">xml001</controlfield>
        <controlfield tag="008">240101s2024    ch            000 0 chi  </controlfield>
        <datafield tag="245" ind1="1" ind2="0"><subfield code="a">XML 編目 :</subfield></datafield>
      </record>
    </collection>"""


@pytest.mark.django_db
def test_import_batch_parse_does_not_create_catalog_until_approved():
    batch = create_import_batch(
        payload=sample_bibliographic_record(),
        import_format=MarcImportBatch.ImportFormat.ISO2709,
        source="unit-test",
        filename="one.mrc",
    )

    assert batch.records.count() == 1
    assert BibliographicRecord.objects.count() == 0

    parse_import_batch(batch_id=batch.id)
    record = batch.records.get()
    assert record.status == MarcImportRecord.Status.PARSED
    assert record.mapped_json["work"]["primary_title"] == "圖書資訊學導論"
    assert record.authority_suggestions.filter(label="王大明").exists()
    assert BibliographicRecord.objects.count() == 0

    record = approve_import_record(import_record_id=record.id)
    record.refresh_from_db()
    assert record.status == MarcImportRecord.Status.APPROVED
    assert record.bibliographic_record.work.primary_title == "圖書資訊學導論"
    assert record.marc_record is not None


@pytest.mark.django_db
def test_duplicate_control_number_is_marked_conflict():
    BibliographicRecord.objects.create(source="dup", control_number="ocn123456789")
    batch = create_import_batch(
        payload=sample_bibliographic_record(),
        import_format=MarcImportBatch.ImportFormat.ISO2709,
        source="dup",
    )

    parse_import_batch(batch_id=batch.id)
    record = batch.records.get()

    assert record.status == MarcImportRecord.Status.CONFLICT
    assert "Existing bibliographic record" in record.conflict_reason


def test_marcxml_and_json_parse_to_canonical_schema():
    xml_record = parse_marcxml_records(sample_marcxml_payload())[0]["parsed"]
    json_record = parse_json_marc_records(sample_json_marc_payload())[0]["parsed"]

    assert xml_record["fields"][0] == {"tag": "001", "value": "xml001"}
    assert json_record["fields"][0] == {"tag": "001", "value": "json001"}


@pytest.mark.django_db
def test_authority_suggestion_can_create_provisional_and_accept_existing_authority():
    batch = create_import_batch(
        payload=sample_bibliographic_record(),
        import_format=MarcImportBatch.ImportFormat.ISO2709,
        source="auth",
    )
    parse_import_batch(batch_id=batch.id)
    record = batch.records.get()
    record = approve_import_record(import_record_id=record.id)
    suggestion = record.authority_suggestions.get(label="王大明")

    created = create_provisional_authority_from_suggestion(suggestion_id=suggestion.id)
    assert created.status == AuthorityLinkSuggestion.Status.CREATED
    assert created.matched_authority.access_points.get().label == "王大明"

    authority = AuthorityRecord.objects.create(
        authority_type=AuthorityRecord.AuthorityType.SUBJECT,
        source="local",
        control_number="s1",
    )
    AccessPoint.objects.create(
        authority=authority,
        kind=AccessPoint.Kind.AUTHORIZED,
        label="圖書資訊學",
        is_preferred=True,
    )
    subject_suggestion = record.authority_suggestions.get(label="圖書資訊學")
    accepted = accept_authority_suggestion(suggestion_id=subject_suggestion.id, authority_id=authority.id)

    assert accepted.status == AuthorityLinkSuggestion.Status.ACCEPTED
    assert WorkAuthorityLink.objects.filter(work=record.bibliographic_record.work, authority=authority).exists()
