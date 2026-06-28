from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.catalog.models import BibliographicRecord, Instance, Work
from apps.circulation.models import CirculationPolicy, FineFee, HoldRequest, Patron
from apps.circulation.services import checkout_item
from apps.holdings.models import Branch, Holding, Item, Location


@pytest.fixture
def patron_portal_setup():
    work = Work.objects.create(primary_title="讀者帳戶測試")
    instance = Instance.objects.create(work=work, title_statement="讀者帳戶測試")
    BibliographicRecord.objects.create(
        source="portal",
        control_number="PORTAL-001",
        status=BibliographicRecord.Status.APPROVED,
        work=work,
        instance=instance,
    )
    branch = Branch.objects.create(code="portal-main", name="讀者總館")
    location = Location.objects.create(branch=branch, code="open", name="開架")
    holding = Holding.objects.create(instance=instance, branch=branch, location=location)
    item = Item.objects.create(holding=holding, barcode="PORTAL-I001", status=Item.Status.AVAILABLE)
    second_item = Item.objects.create(
        holding=holding, barcode="PORTAL-I002", status=Item.Status.AVAILABLE
    )
    user = get_user_model().objects.create_user(
        username="portal-reader", password="x", email="reader@example.test"
    )
    patron = Patron.objects.create(user=user, barcode="PORTAL-P001", home_branch=branch)
    other_user = get_user_model().objects.create_user(username="portal-other", password="x")
    other_patron = Patron.objects.create(user=other_user, barcode="PORTAL-P002", home_branch=branch)
    CirculationPolicy.objects.create(
        name="Portal policy",
        priority=1,
        patron_type="standard",
        branch=branch,
        location=location,
        resource_type=Instance.ResourceType.BOOK,
        loan_period_days=14,
        renewal_period_days=7,
        max_renewals=2,
        max_open_loans=5,
        max_holds=5,
        overdue_fee_per_day=Decimal("5.00"),
    )
    return {
        "user": user,
        "patron": patron,
        "other_user": other_user,
        "other_patron": other_patron,
        "instance": instance,
        "item": item,
        "second_item": second_item,
        "location": location,
    }


@pytest.mark.django_db
def test_account_requires_login_and_handles_missing_patron():
    client = Client()
    response = client.get(reverse("discovery:account_dashboard"))
    assert response.status_code == 302

    user = get_user_model().objects.create_user(username="no-patron", password="x")
    client.force_login(user)
    response = client.get(reverse("discovery:account_dashboard"))
    assert response.status_code == 200
    assert "尚未建立讀者檔" in response.content.decode()


@pytest.mark.django_db
def test_patron_account_lists_own_loans_holds_and_fees(patron_portal_setup):
    loan = checkout_item(
        item_id=patron_portal_setup["item"].id,
        patron_id=patron_portal_setup["patron"].id,
    )
    HoldRequest.objects.create(
        patron=patron_portal_setup["patron"],
        instance=patron_portal_setup["instance"],
        pickup_location=patron_portal_setup["location"],
    )
    FineFee.objects.create(
        patron=patron_portal_setup["patron"],
        loan=loan,
        reason="Overdue item",
        amount=Decimal("20.00"),
        original_amount=Decimal("20.00"),
        balance_amount=Decimal("20.00"),
    )
    client = Client()
    client.force_login(patron_portal_setup["user"])

    dashboard = client.get(reverse("discovery:account_dashboard"))
    loans = client.get(reverse("discovery:account_loans"))
    holds = client.get(reverse("discovery:account_holds"))
    fees = client.get(reverse("discovery:account_fees"))

    assert dashboard.status_code == 200
    assert "PORTAL-P001" in dashboard.content.decode()
    assert "讀者帳戶測試" in loans.content.decode()
    assert "queued" in holds.content.decode()
    assert "20.00" in fees.content.decode()


@pytest.mark.django_db
def test_patron_can_renew_own_loan_and_cancel_own_hold(patron_portal_setup):
    loan = checkout_item(
        item_id=patron_portal_setup["item"].id,
        patron_id=patron_portal_setup["patron"].id,
    )
    original_due = loan.due_at
    client = Client()
    client.force_login(patron_portal_setup["user"])

    renew = client.post(reverse("discovery:account_renew_loan", args=[loan.id]))

    hold = HoldRequest.objects.create(
        patron=patron_portal_setup["patron"],
        instance=patron_portal_setup["instance"],
        pickup_location=patron_portal_setup["location"],
    )
    cancel = client.post(reverse("discovery:account_cancel_hold", args=[hold.id]))

    loan.refresh_from_db()
    hold.refresh_from_db()
    assert renew.status_code == 302
    assert cancel.status_code == 302
    assert loan.due_at > original_due
    assert hold.status == HoldRequest.Status.CANCELLED


@pytest.mark.django_db
def test_patron_cannot_cancel_another_patron_hold(patron_portal_setup):
    hold = HoldRequest.objects.create(
        patron=patron_portal_setup["other_patron"],
        instance=patron_portal_setup["instance"],
        pickup_location=patron_portal_setup["location"],
    )
    client = Client()
    client.force_login(patron_portal_setup["user"])

    response = client.post(reverse("discovery:account_cancel_hold", args=[hold.id]))

    assert response.status_code == 404


@pytest.mark.django_db
def test_opac_record_detail_allows_authenticated_patron_hold(patron_portal_setup):
    client = Client()
    client.force_login(patron_portal_setup["user"])

    detail = client.get(
        reverse("discovery:record_detail", args=[patron_portal_setup["instance"].id])
    )
    response = client.post(
        reverse("discovery:record_place_hold", args=[patron_portal_setup["instance"].id])
    )

    assert detail.status_code == 200
    assert "預約此書" in detail.content.decode()
    assert response.status_code == 302
    assert HoldRequest.objects.filter(
        patron=patron_portal_setup["patron"],
        instance=patron_portal_setup["instance"],
        status=HoldRequest.Status.QUEUED,
    ).exists()
