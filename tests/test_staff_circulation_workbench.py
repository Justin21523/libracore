from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import Instance, Work
from apps.circulation.models import CirculationPolicy, FineFee, HoldRequest, Loan, Patron, Payment
from apps.circulation.services import checkout_item
from apps.holdings.models import Branch, Holding, Item, Location


@pytest.fixture
def staff_circulation_setup():
    work = Work.objects.create(primary_title="館員流通測試")
    instance = Instance.objects.create(work=work, title_statement="館員流通測試")
    branch = Branch.objects.create(code="staff-circ", name="流通總館")
    location = Location.objects.create(branch=branch, code="stack", name="書庫")
    holding = Holding.objects.create(instance=instance, branch=branch, location=location)
    item = Item.objects.create(holding=holding, barcode="SC-I001", status=Item.Status.AVAILABLE)
    second_item = Item.objects.create(
        holding=holding, barcode="SC-I002", status=Item.Status.AVAILABLE
    )
    staff = get_user_model().objects.create_user(username="circ-staff", password="x", is_staff=True)
    user = get_user_model().objects.create_user(
        username="circ-reader", password="x", email="reader@example.test"
    )
    patron = Patron.objects.create(user=user, barcode="SC-P001", home_branch=branch)
    other_user = get_user_model().objects.create_user(username="circ-other", password="x")
    other_patron = Patron.objects.create(user=other_user, barcode="SC-P002", home_branch=branch)
    CirculationPolicy.objects.create(
        name="Staff circulation policy",
        priority=1,
        patron_type="standard",
        branch=branch,
        location=location,
        resource_type=Instance.ResourceType.BOOK,
        loan_period_days=14,
        renewal_period_days=7,
        max_renewals=2,
        max_open_loans=10,
        max_holds=10,
        hold_shelf_days=5,
        overdue_fee_per_day=Decimal("5.00"),
    )
    client = Client()
    client.force_login(staff)
    return {
        "client": client,
        "staff": staff,
        "instance": instance,
        "branch": branch,
        "location": location,
        "item": item,
        "second_item": second_item,
        "patron": patron,
        "other_patron": other_patron,
    }


@pytest.mark.django_db
def test_circulation_desk_lookup_checkout_renew_and_return_with_ready_hold(staff_circulation_setup):
    client = staff_circulation_setup["client"]
    patron = staff_circulation_setup["patron"]
    item = staff_circulation_setup["item"]

    desk = client.get(
        reverse("staff:circulation_desk"),
        {"patron_barcode": patron.barcode, "item_barcode": item.barcode},
    )
    checkout = client.post(
        reverse("staff:circulation_checkout"),
        {"patron_barcode": patron.barcode, "item_barcode": item.barcode},
        follow=True,
    )
    loan = Loan.objects.get(patron=patron, item=item)
    original_due = loan.due_at
    renew = client.post(reverse("staff:circulation_renew", args=[loan.id]), follow=True)
    HoldRequest.objects.create(
        patron=staff_circulation_setup["other_patron"],
        instance=staff_circulation_setup["instance"],
        pickup_location=staff_circulation_setup["location"],
    )
    returned = client.post(
        reverse("staff:circulation_return"),
        {"item_barcode": item.barcode},
        follow=True,
    )

    item.refresh_from_db()
    loan.refresh_from_db()
    assert desk.status_code == 200
    assert "SC-P001" in desk.content.decode()
    assert checkout.status_code == 200
    assert renew.status_code == 200
    assert loan.due_at > original_due
    assert returned.status_code == 200
    assert "已轉入待取" in returned.content.decode()
    assert item.status == Item.Status.ON_HOLD
    assert HoldRequest.objects.filter(status=HoldRequest.Status.READY, item=item).exists()


@pytest.mark.django_db
def test_patron_management_new_edit_and_detail(staff_circulation_setup):
    client = staff_circulation_setup["client"]
    new_user = get_user_model().objects.create_user(
        username="new-patron-user", email="new@example.test"
    )

    created = client.post(
        reverse("staff:patron_new"),
        {
            "user_id": new_user.id,
            "barcode": "SC-P003",
            "patron_type": "faculty",
            "expiry_date": "2027-12-31",
            "home_branch_id": staff_circulation_setup["branch"].id,
            "privacy_opt_in": "on",
        },
    )
    patron = Patron.objects.get(barcode="SC-P003")
    edited = client.post(
        reverse("staff:patron_edit", args=[patron.id]),
        {
            "user_id": new_user.id,
            "barcode": "SC-P003-EDIT",
            "patron_type": "graduate",
            "expiry_date": "",
            "home_branch_id": "",
        },
    )
    list_response = client.get(reverse("staff:patron_list"), {"q": "SC-P003-EDIT"})
    detail = client.get(reverse("staff:patron_detail", args=[patron.id]))

    patron.refresh_from_db()
    assert created.status_code == 302
    assert edited.status_code == 302
    assert patron.barcode == "SC-P003-EDIT"
    assert patron.patron_type == "graduate"
    assert patron.expiry_date is None
    assert "SC-P003-EDIT" in list_response.content.decode()
    assert detail.status_code == 200


@pytest.mark.django_db
def test_fee_payment_and_waiver_workbench_updates_balances(staff_circulation_setup):
    client = staff_circulation_setup["client"]
    patron = staff_circulation_setup["patron"]

    fee_response = client.post(
        reverse("staff:patron_add_fee", args=[patron.id]),
        {"reason": "Replacement card", "amount": "30.00", "note": "manual"},
    )
    fee = FineFee.objects.get(patron=patron, reason="Replacement card")
    payment_response = client.post(
        reverse("staff:patron_record_payment", args=[patron.id]),
        {"amount": "10.00", "method": Payment.Method.CASH, "reference": "R001"},
    )
    fee.refresh_from_db()
    waive_response = client.post(
        reverse("staff:fee_waive", args=[fee.id]),
        {"amount": "20.00", "reason": "approved"},
    )
    fee.refresh_from_db()
    fee_list = client.get(reverse("staff:fee_list"))
    payment_list = client.get(reverse("staff:payment_list"))

    assert fee_response.status_code == 302
    assert payment_response.status_code == 302
    assert waive_response.status_code == 302
    assert fee.balance_amount == Decimal("0.00")
    assert fee.status == FineFee.Status.WAIVED
    assert "Replacement card" in fee_list.content.decode()
    assert "R001" in payment_list.content.decode()


@pytest.mark.django_db
def test_circulation_reports_show_daily_and_exception_lists(staff_circulation_setup):
    patron = staff_circulation_setup["patron"]
    item = staff_circulation_setup["item"]
    second_item = staff_circulation_setup["second_item"]
    loan = checkout_item(item_id=item.id, patron_id=patron.id)
    loan.due_at = timezone.now() - timezone.timedelta(days=2)
    loan.save(update_fields=["due_at"])
    HoldRequest.objects.create(
        patron=staff_circulation_setup["other_patron"],
        instance=staff_circulation_setup["instance"],
        item=second_item,
        pickup_location=staff_circulation_setup["location"],
        status=HoldRequest.Status.READY,
        expires_at=timezone.now() + timezone.timedelta(days=5),
    )
    FineFee.objects.create(
        patron=patron,
        reason="High balance",
        amount=Decimal("1200.00"),
        original_amount=Decimal("1200.00"),
        balance_amount=Decimal("1200.00"),
    )
    second_item.status = Item.Status.MISSING
    second_item.save(update_fields=["status"])

    response = staff_circulation_setup["client"].get(reverse("staff:circulation_reports"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "SC-I001" in content
    assert "預約待取" in content
    assert "SC-P001" in content
    assert "SC-I002" in content
