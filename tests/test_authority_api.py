import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.authorities.models import AccessPoint, AuthorityRecord
from apps.authorities.services import create_authority


@pytest.mark.django_db
def test_staff_can_create_add_variant_and_merge_authority_via_api():
    staff = get_user_model().objects.create_user(username="authority-staff", password="x", is_staff=True)
    client = APIClient()
    client.force_authenticate(staff)

    created = client.post(
        "/api/authorities/",
        {"authority_type": "person", "preferred_label": "王大明", "source": "local"},
        format="json",
    )
    assert created.status_code == 201

    variant = client.post(
        f"/api/authorities/{created.data['id']}/add-variant/",
        {"label": "Wang Daming", "kind": "variant"},
        format="json",
    )
    assert variant.status_code == 201

    target = create_authority(authority_type=AuthorityRecord.AuthorityType.PERSON, preferred_label="王大明教授")
    merged = client.post(
        f"/api/authorities/{created.data['id']}/merge/",
        {"target_id": str(target.id), "note": "duplicate"},
        format="json",
    )
    assert merged.status_code == 200
    assert AuthorityRecord.objects.get(id=created.data["id"]).status == AuthorityRecord.Status.DEPRECATED


@pytest.mark.django_db
def test_non_staff_cannot_mutate_authority():
    user = get_user_model().objects.create_user(username="authority-reader", password="x")
    client = APIClient()
    client.force_authenticate(user)

    response = client.post(
        "/api/authorities/",
        {"authority_type": "person", "preferred_label": "王大明"},
        format="json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_public_browse_and_external_identifier_validation():
    authority = create_authority(authority_type=AuthorityRecord.AuthorityType.PERSON, preferred_label="王大明")
    response = APIClient().get("/api/authorities/browse/", {"q": "王"})
    assert response.status_code == 200
    assert response.data[0]["preferred_label"] == "王大明"

    staff = get_user_model().objects.create_user(username="external-staff", password="x", is_staff=True)
    client = APIClient()
    client.force_authenticate(staff)
    bad = client.post(
        "/api/authority-identifiers/",
        {"authority": str(authority.id), "scheme": "orcid", "value": "bad", "uri": "https://example.com/bad"},
        format="json",
    )
    assert bad.status_code == 400
