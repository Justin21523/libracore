import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from apps.authorities.models import AccessPoint, AuthorityRecord
from apps.catalog.models import BibliographicRecord, Instance, Work
from apps.core.roles import ROLE_CATALOGER, seed_role_groups
from apps.holdings.models import Branch, Holding, Item, Location
from apps.marc.models import MarcImportBatch, MarcImportRecord, MarcMatchCandidate, MarcRecord
from apps.marc.review_services import approve_import_record, create_import_batch, parse_import_batch
from tests.test_marc_parser import sample_bibliographic_record


def build_marc_record(fields, leader_template="00000nam a2200000 i 4500"):
    chunks = []
    directory = ""
    position = 0
    for tag, content in fields:
        data = content + "\x1e"
        length = len(data)
        directory += f"{tag}{length:04d}{position:05d}"
        chunks.append(data)
        position += length
    base_address = 24 + len(directory) + 1
    record_body = directory + "\x1e" + "".join(chunks) + "\x1d"
    record_length = 24 + len(record_body)
    leader = (
        f"{record_length:05d}"
        + leader_template[5:12]
        + f"{base_address:05d}"
        + leader_template[17:]
    )
    return (leader + record_body).encode()


def sample_authority_record():
    return build_marc_record(
        [
            ("001", "auth001"),
            ("003", "DLC"),
            ("100", "1 " + "\x1f" + "a王大明," + "\x1f" + "d1970-"),
            ("400", "1 " + "\x1f" + "aWang, Daming,"),
            ("667", "  " + "\x1f" + "aLocal test authority."),
        ],
        leader_template="00000nz  a2200000n  4500",
    )


def sample_holdings_record():
    return build_marc_record(
        [
            ("001", "hold001"),
            ("004", "BIB-HOLD-001"),
            (
                "852",
                "  "
                + "\x1f"
                + "bhmain"
                + "\x1f"
                + "cstacks"
                + "\x1f"
                + "h020"
                + "\x1f"
                + "iW25"
                + "\x1f"
                + "zPublic holdings note",
            ),
            ("866", "  " + "\x1f" + "av.1-v.3"),
            ("876", "  " + "\x1f" + "pHOLD-ITEM-1" + "\x1f" + "t1" + "\x1f" + "javailable"),
        ],
        leader_template="00000ny  a2200000n  4500",
    )


def cataloger_user(username="marc-deep-cataloger"):
    seed_role_groups()
    user = get_user_model().objects.create_user(username=username, password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=ROLE_CATALOGER))
    return user


@pytest.fixture
def holdings_catalog_setup():
    work = Work.objects.create(primary_title="館藏 MARC 測試")
    instance = Instance.objects.create(work=work, title_statement="館藏 MARC 測試")
    bib = BibliographicRecord.objects.create(
        source="local",
        control_number="BIB-HOLD-001",
        status=BibliographicRecord.Status.APPROVED,
        work=work,
        instance=instance,
    )
    branch = Branch.objects.create(code="hmain", name="館藏總館")
    location = Location.objects.create(branch=branch, code="stacks", name="一般書庫")
    return {"work": work, "instance": instance, "bib": bib, "branch": branch, "location": location}


@pytest.mark.django_db
def test_authority_marc_import_creates_authority_access_points_and_marc_record():
    batch = create_import_batch(
        payload=sample_authority_record(),
        import_format=MarcImportBatch.ImportFormat.ISO2709,
        source="auth-src",
    )

    parse_import_batch(batch_id=batch.id)
    record = batch.records.get()
    assert record.format_type == MarcRecord.FormatType.AUTHORITY
    assert record.status == MarcImportRecord.Status.PARSED
    assert record.mapped_json["authority"]["preferred_label"] == "王大明, 1970-"

    approved = approve_import_record(import_record_id=record.id)
    authority = approved.authority_record

    assert approved.status == MarcImportRecord.Status.APPROVED
    assert authority.control_number == "auth001"
    assert authority.authority_type == AuthorityRecord.AuthorityType.PERSON
    assert AccessPoint.objects.filter(authority=authority, label="Wang, Daming").exists()
    assert approved.marc_record.authority_record == authority


@pytest.mark.django_db
def test_holdings_marc_import_creates_holding_item_and_links_marc(holdings_catalog_setup):
    batch = create_import_batch(
        payload=sample_holdings_record(),
        import_format=MarcImportBatch.ImportFormat.ISO2709,
        source="hold-src",
    )

    parse_import_batch(batch_id=batch.id)
    record = batch.records.get()
    assert record.format_type == MarcRecord.FormatType.HOLDINGS
    assert record.status == MarcImportRecord.Status.PARSED
    assert MarcMatchCandidate.objects.filter(
        import_record=record,
        match_rule="004_bibliographic_control_number",
    ).exists()

    approved = approve_import_record(import_record_id=record.id)

    assert approved.status == MarcImportRecord.Status.APPROVED
    assert approved.holding.instance == holdings_catalog_setup["instance"]
    assert approved.holding.textual_holdings == "v.1-v.3"
    assert Item.objects.filter(barcode="HOLD-ITEM-1", holding=approved.holding).exists()
    assert approved.marc_record.holding == approved.holding


@pytest.mark.django_db
def test_duplicate_bibliographic_import_can_link_existing_record():
    work = Work.objects.create(primary_title="Existing")
    instance = Instance.objects.create(work=work, title_statement="Existing")
    bib = BibliographicRecord.objects.create(
        source="dup",
        control_number="ocn123456789",
        status=BibliographicRecord.Status.APPROVED,
        work=work,
        instance=instance,
    )
    batch = create_import_batch(
        payload=sample_bibliographic_record(),
        import_format=MarcImportBatch.ImportFormat.ISO2709,
        source="dup",
    )
    parse_import_batch(batch_id=batch.id)
    record = batch.records.get()

    assert record.status == MarcImportRecord.Status.CONFLICT
    assert record.match_candidates.filter(match_rule="source_control_number").exists()

    api = APIClient()
    api.force_authenticate(cataloger_user("marc-resolve-api"))
    response = api.post(
        f"/api/marc-import-records/{record.id}/resolve/",
        {"action": "link_existing", "target_id": str(bib.id)},
        format="json",
    )
    record.refresh_from_db()

    assert response.status_code == 200
    assert record.status == MarcImportRecord.Status.APPROVED
    assert record.bibliographic_record == bib
    assert (
        BibliographicRecord.objects.filter(source="dup", control_number="ocn123456789").count() == 1
    )


@pytest.mark.django_db
def test_staff_review_page_displays_candidates_and_resolves_holdings(holdings_catalog_setup):
    staff = cataloger_user("marc-resolve-ui")
    batch = create_import_batch(
        payload=sample_holdings_record(),
        import_format=MarcImportBatch.ImportFormat.ISO2709,
        source="hold-ui",
    )
    parse_import_batch(batch_id=batch.id)
    record = batch.records.get()
    client = Client()
    client.force_login(staff)

    page = client.get(reverse("staff:import_record_review", args=[record.id]))
    resolved = client.post(
        reverse("staff:import_record_resolve", args=[record.id]),
        {"action": "create_new"},
    )
    record.refresh_from_db()

    assert page.status_code == 200
    assert "004_bibliographic_control_number" in page.content.decode()
    assert resolved.status_code == 302
    assert record.status == MarcImportRecord.Status.APPROVED
    assert Holding.objects.filter(instance=holdings_catalog_setup["instance"]).exists()
