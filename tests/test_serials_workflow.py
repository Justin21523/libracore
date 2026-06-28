from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from apps.catalog.models import BibliographicRecord, Instance, Work
from apps.discovery.indexing import rebuild_instance_index
from apps.discovery.search import search_documents
from apps.holdings.models import Branch, Holding, Item, Location
from apps.serials.models import (
    BoundVolume,
    Issue,
    IssuePredictionPattern,
    SerialTitle,
    Subscription,
)
from apps.serials.services import (
    bind_issues,
    check_in_issue,
    claim_issue,
    generate_expected_issues,
    mark_issue_missing,
)


@pytest.fixture
def serial_setup():
    work = Work.objects.create(primary_title="圖書館學季刊")
    instance = Instance.objects.create(
        work=work,
        resource_type=Instance.ResourceType.SERIAL,
        title_statement="圖書館學季刊",
        identifiers=[{"scheme": "issn", "value": "1234-5678"}],
    )
    BibliographicRecord.objects.create(
        source="serials",
        control_number="SER-001",
        status=BibliographicRecord.Status.APPROVED,
        work=work,
        instance=instance,
    )
    branch = Branch.objects.create(code="serial-main", name="總館期刊")
    location = Location.objects.create(branch=branch, code="periodicals", name="期刊室")
    serial = SerialTitle.objects.create(
        instance=instance, title="圖書館學季刊", issn="1234-5678", frequency="季刊"
    )
    subscription = Subscription.objects.create(
        serial_title=serial, branch=branch, location=location
    )
    IssuePredictionPattern.objects.create(
        subscription=subscription,
        frequency=IssuePredictionPattern.Frequency.QUARTERLY,
        next_volume=12,
        next_number=1,
        next_expected_at=date(2026, 1, 1),
        issues_per_volume=4,
    )
    return {
        "instance": instance,
        "branch": branch,
        "location": location,
        "serial": serial,
        "subscription": subscription,
    }


@pytest.mark.django_db
def test_serial_prediction_checkin_claim_missing_and_binding(serial_setup):
    issues = generate_expected_issues(subscription_id=serial_setup["subscription"].id, count=2)

    assert [issue.enumeration for issue in issues] == ["v. 12 no. 1", "v. 12 no. 2"]
    checked_in = check_in_issue(issue_id=issues[0].id)
    assert checked_in.status == Issue.Status.RECEIVED
    assert checked_in.item and checked_in.item.barcode.startswith("SER-")
    assert Holding.objects.filter(
        instance=serial_setup["instance"], textual_holdings__contains="v. 12 no. 1"
    ).exists()

    mark_issue_missing(issue_id=issues[1].id)
    claim_event = claim_issue(issue_id=issues[1].id, note="供應商補寄中")
    issues[1].refresh_from_db()
    assert issues[1].status == Issue.Status.MISSING
    assert issues[1].claim_count == 1
    assert claim_event.note == "供應商補寄中"

    bound = bind_issues(issue_ids=[checked_in.id], label="第12卷合訂本")
    checked_in.refresh_from_db()
    assert isinstance(bound, BoundVolume)
    assert checked_in.status == Issue.Status.BOUND
    assert Item.objects.filter(barcode__startswith="BND-").exists()


@pytest.mark.django_db
def test_serial_api_generates_and_checks_in_issue(serial_setup):
    staff = get_user_model().objects.create_user(username="ser-api", password="x", is_staff=True)
    client = APIClient()
    client.force_authenticate(staff)

    response = client.post(
        f"/api/subscriptions/{serial_setup['subscription'].id}/generate-issues/",
        {"count": 1},
        format="json",
    )
    assert response.status_code == 201
    issue_id = response.data[0]["id"]

    response = client.post(f"/api/issues/{issue_id}/check-in/")

    assert response.status_code == 200
    assert response.data["status"] == Issue.Status.RECEIVED


@pytest.mark.django_db
def test_staff_serial_views_and_opac_serial_holdings(serial_setup):
    staff = get_user_model().objects.create_user(username="ser-view", password="x", is_staff=True)
    client = Client()
    client.force_login(staff)

    subscription_detail = client.get(
        reverse("staff:subscription_detail", args=[serial_setup["subscription"].id])
    )
    assert subscription_detail.status_code == 200
    assert "圖書館學季刊" in subscription_detail.content.decode()

    response = client.post(
        reverse("staff:subscription_generate_issues", args=[serial_setup["subscription"].id]),
        {"count": "1"},
    )
    assert response.status_code == 302
    issue = Issue.objects.get()

    response = client.post(reverse("staff:issue_check_in", args=[issue.id]))
    assert response.status_code == 302

    detail = client.get(reverse("discovery:record_detail", args=[serial_setup["instance"].id]))
    content = detail.content.decode()
    assert "期刊館藏" in content
    assert "v. 12 no. 1" in content


@pytest.mark.django_db
def test_discovery_indexes_serial_holdings_and_issue_text(serial_setup):
    issue = generate_expected_issues(subscription_id=serial_setup["subscription"].id, count=1)[0]
    check_in_issue(issue_id=issue.id)

    document = rebuild_instance_index(serial_setup["instance"].id)
    results = search_documents(query="v. 12 no. 1")

    assert document.facets["serial_frequency"] == ["季刊"]
    assert document.facets["serial_status"] == [Issue.Status.RECEIVED]
    assert results.total == 1
