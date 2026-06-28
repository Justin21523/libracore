from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.catalog.models import Instance, Work
from apps.circulation.models import CirculationPolicy, FineFee, Patron
from apps.holdings.models import Branch, Holding, Item, Location


@pytest.fixture
def api_setup():
    work = Work.objects.create(primary_title="API 流通測試")
    instance = Instance.objects.create(work=work, title_statement="API 流通測試")
    branch = Branch.objects.create(code="api", name="API 館")
    location = Location.objects.create(branch=branch, code="stack", name="一般書庫")
    holding = Holding.objects.create(instance=instance, branch=branch, location=location)
    item = Item.objects.create(holding=holding, barcode="API001", status=Item.Status.AVAILABLE)
    patron_user = get_user_model().objects.create_user(username="api-reader")
    patron = Patron.objects.create(user=patron_user, barcode="APIP001", home_branch=branch)
    staff = get_user_model().objects.create_user(username="staff", password="x", is_staff=True)
    normal = get_user_model().objects.create_user(username="normal", password="x")
    CirculationPolicy.objects.create(
        name="API policy",
        priority=1,
        patron_type="standard",
        branch=branch,
        location=location,
        resource_type=Instance.ResourceType.BOOK,
        overdue_fee_per_day=Decimal("5.00"),
    )
    return {"item": item, "patron": patron, "staff": staff, "normal": normal}


@pytest.mark.django_db
def test_staff_can_checkout_and_return_via_api(api_setup):
    client = APIClient()
    client.force_authenticate(api_setup["staff"])

    checkout = client.post(
        "/api/circulation/checkout/",
        {"item_id": api_setup["item"].id, "patron_id": api_setup["patron"].id},
        format="json",
    )
    assert checkout.status_code == 201
    loan_id = checkout.data["id"]

    returned = client.post(f"/api/loans/{loan_id}/return-item/")
    assert returned.status_code == 200
    assert returned.data["status"] == "returned"


@pytest.mark.django_db
def test_non_staff_cannot_mutate_circulation(api_setup):
    client = APIClient()
    client.force_authenticate(api_setup["normal"])

    response = client.post(
        "/api/circulation/checkout/",
        {"item_id": api_setup["item"].id, "patron_id": api_setup["patron"].id},
        format="json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_payment_api_records_staff_payment(api_setup):
    fee = FineFee.objects.create(
        patron=api_setup["patron"],
        fee_type=FineFee.FeeType.MANUAL,
        reason="Manual fee",
        amount=Decimal("25.00"),
        original_amount=Decimal("25.00"),
        balance_amount=Decimal("25.00"),
    )
    client = APIClient()
    client.force_authenticate(api_setup["staff"])

    response = client.post(
        "/api/payments/",
        {"patron_id": api_setup["patron"].id, "amount": "25.00", "method": "cash"},
        format="json",
    )

    assert response.status_code == 201
    fee.refresh_from_db()
    assert fee.balance_amount == Decimal("0.00")
    assert fee.status == FineFee.Status.PAID

