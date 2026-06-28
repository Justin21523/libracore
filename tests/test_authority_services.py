import pytest

from apps.authorities.models import AccessPoint, AuthorityRecord, AuthorityRelation
from apps.authorities.services import (
    add_access_point,
    add_authority_relation,
    create_authority,
    merge_authorities,
    set_preferred_access_point,
)
from apps.catalog.models import BibliographicRecord, Instance, Work, WorkAuthorityLink
from apps.core.models import AuditLog
from apps.discovery.indexing import rebuild_instance_index
from apps.discovery.search import search_documents


@pytest.mark.django_db
def test_create_authority_creates_preferred_access_point():
    authority = create_authority(
        authority_type=AuthorityRecord.AuthorityType.PERSON,
        preferred_label="王大明",
    )

    access_point = authority.access_points.get()
    assert access_point.kind == AccessPoint.Kind.AUTHORIZED
    assert access_point.is_preferred is True
    assert access_point.normalized_label


@pytest.mark.django_db
def test_set_preferred_access_point_unsets_previous():
    authority = create_authority(
        authority_type=AuthorityRecord.AuthorityType.PERSON,
        preferred_label="王大明",
    )
    new_point = add_access_point(
        authority_id=authority.id,
        label="Wang, Daming",
        kind=AccessPoint.Kind.AUTHORIZED,
        is_preferred=False,
    )

    set_preferred_access_point(authority_id=authority.id, access_point_id=new_point.id)

    assert authority.access_points.filter(is_preferred=True).get().id == new_point.id


@pytest.mark.django_db
def test_relation_and_merge_transfer_links_and_deprecate_source():
    source = create_authority(
        authority_type=AuthorityRecord.AuthorityType.SUBJECT,
        preferred_label="圖書館學",
    )
    target = create_authority(
        authority_type=AuthorityRecord.AuthorityType.SUBJECT,
        preferred_label="圖書資訊學",
    )
    add_authority_relation(
        source_id=source.id,
        target_id=target.id,
        relation_type=AuthorityRelation.RelationType.RELATED,
    )
    work = Work.objects.create(primary_title="權威控制")
    instance = Instance.objects.create(work=work, title_statement="權威控制")
    BibliographicRecord.objects.create(
        source="auth",
        control_number="auth001",
        status=BibliographicRecord.Status.APPROVED,
        work=work,
        instance=instance,
    )
    WorkAuthorityLink.objects.create(work=work, authority=source, role=WorkAuthorityLink.Role.SUBJECT)

    merge_authorities(source_id=source.id, target_id=target.id, note="duplicate")
    source.refresh_from_db()

    assert source.status == AuthorityRecord.Status.DEPRECATED
    assert source.deprecated_replacement == target
    assert WorkAuthorityLink.objects.filter(work=work, authority=target).exists()
    assert target.access_points.filter(label="圖書館學", kind=AccessPoint.Kind.VARIANT).exists()
    assert AuditLog.objects.filter(action="authority_merged").exists()


@pytest.mark.django_db
def test_discovery_index_includes_authority_variant_labels():
    authority = create_authority(
        authority_type=AuthorityRecord.AuthorityType.PERSON,
        preferred_label="王大明",
    )
    add_access_point(authority_id=authority.id, label="Wang Daming", kind=AccessPoint.Kind.VARIANT)
    work = Work.objects.create(primary_title="資料組織")
    instance = Instance.objects.create(work=work, title_statement="資料組織")
    BibliographicRecord.objects.create(
        source="disc",
        control_number="disc001",
        status=BibliographicRecord.Status.APPROVED,
        work=work,
        instance=instance,
    )
    WorkAuthorityLink.objects.create(work=work, authority=authority, role=WorkAuthorityLink.Role.CREATOR)

    rebuild_instance_index(instance.id)
    results = search_documents(query="Wang Daming")

    assert results.total == 1

