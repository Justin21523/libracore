from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.catalog.models import Instance, Work
from apps.circulation.models import CirculationPolicy, Loan, Patron
from apps.holdings.models import Branch, Holding, Item, Location
from apps.interop.circulation_adapter import (
    checkin,
    checkout,
    hold,
    item_status,
    patron_status,
    renew,
)


@pytest.fixture
def adapter_setup():
    work = Work.objects.create(primary_title="Adapter Circulation")
    instance = Instance.objects.create(work=work, title_statement="Adapter Circulation")
    branch = Branch.objects.create(code="main", name="Main")
    location = Location.objects.create(branch=branch, code="stack", name="Stacks")
    holding = Holding.objects.create(instance=instance, branch=branch, location=location)
    item = Item.objects.create(holding=holding, barcode="A-ITEM-1", status=Item.Status.AVAILABLE)
    second_item = Item.objects.create(
        holding=holding,
        barcode="A-ITEM-2",
        status=Item.Status.AVAILABLE,
    )
    user = get_user_model().objects.create_user(username="adapter-reader")
    patron = Patron.objects.create(user=user, barcode="A-PATRON-1", home_branch=branch)
    CirculationPolicy.objects.create(
        name="Adapter policy",
        priority=1,
        patron_type="standard",
        branch=branch,
        location=location,
        resource_type=Instance.ResourceType.BOOK,
        loan_period_days=14,
        renewal_period_days=7,
        max_renewals=1,
        max_open_loans=5,
        max_holds=3,
        overdue_fee_per_day=Decimal("0.00"),
    )
    return {
        "instance": instance,
        "location": location,
        "item": item,
        "second_item": second_item,
        "patron": patron,
    }


@pytest.mark.django_db
def test_adapter_reports_patron_and_item_status(adapter_setup):
    patron_payload = patron_status("A-PATRON-1")
    item_payload = item_status("A-ITEM-1")

    assert patron_payload["ok"] is True
    assert patron_payload["open_loans"] == 0
    assert item_payload["ok"] is True
    assert item_payload["item"]["status"] == Item.Status.AVAILABLE


@pytest.mark.django_db
def test_adapter_checkout_renew_and_checkin(adapter_setup):
    checkout_payload = checkout("A-PATRON-1", "A-ITEM-1")
    renew_payload = renew("A-PATRON-1", "A-ITEM-1")
    checkin_payload = checkin("A-ITEM-1")

    adapter_setup["item"].refresh_from_db()
    assert checkout_payload["ok"] is True
    assert renew_payload["ok"] is True
    assert checkin_payload["ok"] is True
    assert checkin_payload["loan"]["status"] == Loan.Status.RETURNED
    assert adapter_setup["item"].status == Item.Status.AVAILABLE


@pytest.mark.django_db
def test_adapter_places_hold_and_reports_errors(adapter_setup):
    hold_payload = hold(
        "A-PATRON-1",
        pickup_location_id=adapter_setup["location"].id,
        instance_id=adapter_setup["instance"].id,
    )
    missing_item = item_status("NO-SUCH-ITEM")

    assert hold_payload["ok"] is True
    assert hold_payload["hold"]["status"] == "queued"
    assert missing_item == {
        "ok": False,
        "code": "item_not_found",
        "message": "Item not found.",
    }
