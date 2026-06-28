import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.authorities.models import AuthorityRecord
from apps.authorities.services import create_authority


@pytest.mark.django_db
def test_staff_authority_views_render(client):
    staff = get_user_model().objects.create_user(username="authority-view", password="x", is_staff=True)
    client.force_login(staff)
    authority = create_authority(
        authority_type=AuthorityRecord.AuthorityType.SUBJECT,
        preferred_label="圖書資訊學",
    )

    assert client.get(reverse("staff:authority_list")).status_code == 200
    detail = client.get(reverse("staff:authority_detail", args=[authority.id]))
    assert detail.status_code == 200
    assert "圖書資訊學" in detail.content.decode()


@pytest.mark.django_db
def test_public_authority_browse_and_detail_render(client):
    authority = create_authority(
        authority_type=AuthorityRecord.AuthorityType.SUBJECT,
        preferred_label="圖書資訊學",
    )

    browse = client.get(reverse("authorities:browse"), {"q": "圖書"})
    assert browse.status_code == 200
    assert "圖書資訊學" in browse.content.decode()

    subjects = client.get(reverse("authorities:subjects"))
    assert subjects.status_code == 200
    assert "圖書資訊學" in subjects.content.decode()

    detail = client.get(reverse("authorities:detail", args=[authority.id]))
    assert detail.status_code == 200
    assert "正式標目" in detail.content.decode()

