import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from apps.catalog.models import BibliographicRecord, Instance, Work
from apps.core.data_quality import run_data_quality_checks
from apps.core.models import DataQualityIssue
from apps.core.roles import ROLE_REPOSITORY, seed_role_groups
from apps.discovery.indexing import rebuild_instance_index
from apps.discovery.search import search_documents
from apps.repository.models import DigitalObject, FileAsset
from apps.repository.services import publish_object


@pytest.fixture
def repository_setup():
    work = Work.objects.create(primary_title="數位典藏測試", language_hint="chi")
    instance = Instance.objects.create(
        work=work,
        title_statement="數位典藏測試",
        publisher="典藏出版社",
        publication_date="2026",
    )
    bib = BibliographicRecord.objects.create(
        source="repo",
        control_number="REPO-001",
        status=BibliographicRecord.Status.APPROVED,
        work=work,
        instance=instance,
    )
    return {"work": work, "instance": instance, "bib": bib}


def repository_staff(username="repo-staff"):
    seed_role_groups()
    user = get_user_model().objects.create_user(username=username, password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=ROLE_REPOSITORY))
    return user


@pytest.mark.django_db
def test_repository_staff_ui_create_upload_publish_and_public_detail(repository_setup):
    staff = repository_staff()
    client = Client()
    client.force_login(staff)

    created = client.post(
        reverse("staff:repository_object_new"),
        {
            "title": "手稿影像",
            "bibliographic_record_id": repository_setup["bib"].id,
            "status": DigitalObject.Status.DRAFT,
            "dc_title": "手稿影像",
            "dc_creator": "王大明",
            "dc_subject": "地方文獻",
            "dc_type": "Text",
            "rights_statement": "Open access",
        },
    )
    obj = DigitalObject.objects.get(title="手稿影像")
    uploaded = client.post(
        reverse("staff:repository_file_upload", args=[obj.id]),
        {
            "label": "全文",
            "access_level": "public",
            "file": SimpleUploadedFile(
                "fulltext.txt",
                "地方文獻全文 OCR".encode(),
                content_type="text/plain",
            ),
        },
    )
    published = client.post(reverse("staff:repository_object_publish", args=[obj.id]))
    obj.refresh_from_db()
    public_detail = client.get(reverse("repository:detail", args=[obj.id]))

    assert created.status_code == 302
    assert uploaded.status_code == 302
    assert published.status_code == 302
    assert obj.status == DigitalObject.Status.PUBLISHED
    assert obj.oai_identifier == f"oai:libracore:repository:{obj.id}"
    assert "手稿影像" in public_detail.content.decode()
    assert "全文" in public_detail.content.decode()


@pytest.mark.django_db
def test_repository_api_upload_enriches_file_and_public_read_filters(repository_setup):
    staff = repository_staff("repo-api")
    api = APIClient()
    api.force_authenticate(staff)
    draft = api.post(
        "/api/digital-objects/",
        {
            "title": "API 典藏",
            "bibliographic_record": repository_setup["bib"].id,
            "status": DigitalObject.Status.DRAFT,
            "dc_metadata": {"title": "API 典藏", "subject": ["測試"]},
        },
        format="json",
    )
    obj_id = draft.data["id"]
    upload = api.post(
        f"/api/digital-objects/{obj_id}/files/",
        {
            "label": "OCR",
            "access_level": "public",
            "file": SimpleUploadedFile("ocr.txt", b"repository searchable OCR"),
        },
        format="multipart",
    )
    public_before = APIClient().get("/api/digital-objects/")
    publish = api.post(f"/api/digital-objects/{obj_id}/publish/")
    public_after = APIClient().get("/api/digital-objects/")
    asset = FileAsset.objects.get(id=upload.data["id"])

    assert draft.status_code == 201
    assert upload.status_code == 201
    assert asset.checksum_sha256
    assert asset.size_bytes == len(b"repository searchable OCR")
    assert "repository searchable OCR" in asset.ocr_text
    assert public_before.data == []
    assert publish.status_code == 200
    assert public_after.data[0]["title"] == "API 典藏"


@pytest.mark.django_db
def test_repository_public_download_blocks_restricted_file(repository_setup):
    obj = DigitalObject.objects.create(
        title="限制檔案",
        bibliographic_record=repository_setup["bib"],
        status=DigitalObject.Status.PUBLISHED,
        dc_metadata={"title": "限制檔案"},
    )
    public_asset = FileAsset.objects.create(
        digital_object=obj,
        file=SimpleUploadedFile("public.txt", b"public"),
        access_level="public",
        mime_type="text/plain",
    )
    restricted_asset = FileAsset.objects.create(
        digital_object=obj,
        file=SimpleUploadedFile("restricted.txt", b"restricted"),
        access_level="restricted",
        mime_type="text/plain",
    )
    client = Client()

    assert (
        client.get(reverse("repository:file_download", args=[public_asset.id])).status_code == 200
    )
    assert (
        client.get(reverse("repository:file_download", args=[restricted_asset.id])).status_code
        == 403
    )


@pytest.mark.django_db
def test_repository_metadata_and_ocr_are_indexed_for_discovery(repository_setup):
    obj = DigitalObject.objects.create(
        title="地方記憶照片",
        bibliographic_record=repository_setup["bib"],
        status=DigitalObject.Status.PUBLISHED,
        dc_metadata={"title": "地方記憶照片", "subject": "歷史影像"},
    )
    FileAsset.objects.create(
        digital_object=obj,
        file=SimpleUploadedFile("ocr.txt", "特殊 OCR 詞彙".encode()),
        access_level="public",
        mime_type="text/plain",
        ocr_text="特殊 OCR 詞彙",
    )

    document = rebuild_instance_index(repository_setup["instance"].id)
    results = search_documents(query="特殊 OCR", filters={"repository_available": "true"})

    assert document.facets["repository_available"] == ["true"]
    assert document.facets["file_mime_type"] == ["text/plain"]
    assert results.total == 1


@pytest.mark.django_db
def test_oai_repository_records_include_public_identifiers(repository_setup):
    obj = DigitalObject.objects.create(
        title="OAI 典藏",
        bibliographic_record=repository_setup["bib"],
        status=DigitalObject.Status.DRAFT,
        dc_metadata={"title": "OAI 典藏"},
    )
    publish_object(obj)
    asset = FileAsset.objects.create(
        digital_object=obj,
        file=SimpleUploadedFile("oai.txt", b"oai"),
        access_level="public",
        mime_type="text/plain",
    )

    response = Client().get("/oai/", {"verb": "ListRecords", "set": "repository"})
    content = response.content.decode()

    assert f"/repository/{obj.id}/" in content
    assert f"/repository/files/{asset.id}/download/" in content


@pytest.mark.django_db
def test_repository_data_quality_checks(repository_setup):
    DigitalObject.objects.create(
        title="No public file",
        bibliographic_record=repository_setup["bib"],
        status=DigitalObject.Status.PUBLISHED,
        dc_metadata={"title": "No public file"},
    )
    asset = FileAsset.objects.create(
        digital_object=DigitalObject.objects.create(
            title="Missing checksum",
            status=DigitalObject.Status.PUBLISHED,
            dc_metadata={"title": "Missing checksum"},
        ),
        file=SimpleUploadedFile("missing.bin", b"binary"),
        access_level="public",
    )
    asset.checksum_sha256 = ""
    asset.mime_type = ""
    asset.save(update_fields=["checksum_sha256", "mime_type"])

    run_data_quality_checks()
    codes = set(DataQualityIssue.objects.values_list("code", flat=True))

    assert "repository.no_public_file" in codes
    assert "repository.public_file_missing_checksum" in codes
    assert "repository.file_missing_mime_type" in codes
