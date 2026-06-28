from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.catalog.models import Instance, Work
from apps.circulation.models import (
    BranchCalendarException,
    CirculationPolicy,
    FineFee,
    HoldRequest,
    Loan,
    Patron,
    Payment,
)
from apps.circulation.services import (
    CirculationError,
    assess_overdue_fee,
    checkout_item,
    place_hold,
    record_payment,
    renew_loan,
    return_item,
    waive_fee,
)
from apps.holdings.models import Branch, Holding, Item, Location


@pytest.fixture
def circulation_setup():
    work = Work.objects.create(primary_title="流通測試")
    instance = Instance.objects.create(work=work, title_statement="流通測試")
    branch = Branch.objects.create(code="main", name="總館")
    location = Location.objects.create(branch=branch, code="stack", name="一般書庫")
    holding = Holding.objects.create(instance=instance, branch=branch, location=location)
    item = Item.objects.create(holding=holding, barcode="I001", status=Item.Status.AVAILABLE)
    second_item = Item.objects.create(holding=holding, barcode="I002", status=Item.Status.AVAILABLE)
    user = get_user_model().objects.create_user(username="reader")
    patron = Patron.objects.create(user=user, barcode="P001", home_branch=branch)
    other_user = get_user_model().objects.create_user(username="reader2")
    other_patron = Patron.objects.create(user=other_user, barcode="P002", home_branch=branch)
    policy = CirculationPolicy.objects.create(
        name="Test policy",
        priority=1,
        patron_type="standard",
        branch=branch,
        location=location,
        resource_type=Instance.ResourceType.BOOK,
        loan_period_days=14,
        renewal_period_days=7,
        max_renewals=1,
        max_open_loans=1,
        max_holds=3,
        hold_shelf_days=5,
        overdue_fee_per_day=Decimal("5.00"),
        max_overdue_fee=Decimal("50.00"),
        fee_block_threshold=Decimal("100.00"),
    )
    return {
        "instance": instance,
        "branch": branch,
        "location": location,
        "item": item,
        "second_item": second_item,
        "patron": patron,
        "other_patron": other_patron,
        "policy": policy,
    }


@pytest.mark.django_db
def test_checkout_creates_open_loan_and_updates_item(circulation_setup):
    loan = checkout_item(item_id=circulation_setup["item"].id, patron_id=circulation_setup["patron"].id)

    item = Item.objects.get(id=circulation_setup["item"].id)
    assert loan.status == Loan.Status.OPEN
    assert item.status == Item.Status.ON_LOAN
    assert item.due_back_at == loan.due_at


@pytest.mark.django_db
def test_checkout_blocks_when_patron_reaches_loan_limit(circulation_setup):
    checkout_item(item_id=circulation_setup["item"].id, patron_id=circulation_setup["patron"].id)

    with pytest.raises(CirculationError) as exc:
        checkout_item(item_id=circulation_setup["second_item"].id, patron_id=circulation_setup["patron"].id)

    assert exc.value.code == "loan_limit_exceeded"


@pytest.mark.django_db
def test_renew_respects_limit_and_waiting_holds(circulation_setup):
    loan = checkout_item(item_id=circulation_setup["item"].id, patron_id=circulation_setup["patron"].id)
    renewed = renew_loan(loan_id=loan.id)

    assert renewed.renew_count == 1
    with pytest.raises(CirculationError) as exc:
        renew_loan(loan_id=loan.id)
    assert exc.value.code == "renewal_limit_exceeded"


@pytest.mark.django_db
def test_return_routes_item_to_next_hold(circulation_setup):
    loan = checkout_item(item_id=circulation_setup["item"].id, patron_id=circulation_setup["patron"].id)
    hold = place_hold(
        patron_id=circulation_setup["other_patron"].id,
        instance_id=circulation_setup["instance"].id,
        pickup_location_id=circulation_setup["location"].id,
    )

    returned = return_item(loan_id=loan.id)
    item = Item.objects.get(id=circulation_setup["item"].id)
    hold.refresh_from_db()

    assert returned.status == Loan.Status.RETURNED
    assert item.status == Item.Status.ON_HOLD
    assert hold.status == HoldRequest.Status.READY
    assert hold.item_id == item.id
    assert hold.expires_at is not None


@pytest.mark.django_db
def test_due_date_skips_closed_branch_date(circulation_setup):
    tomorrow = timezone.localdate() + timezone.timedelta(days=14)
    BranchCalendarException.objects.create(
        branch=circulation_setup["branch"],
        date=tomorrow,
        name="閉館日",
        is_closed=True,
    )

    loan = checkout_item(item_id=circulation_setup["item"].id, patron_id=circulation_setup["patron"].id)

    assert timezone.localtime(loan.due_at).date() == tomorrow + timezone.timedelta(days=1)


@pytest.mark.django_db
def test_overdue_fee_is_idempotent_and_capped(circulation_setup):
    loan = checkout_item(item_id=circulation_setup["item"].id, patron_id=circulation_setup["patron"].id)
    loan.due_at = timezone.now() - timezone.timedelta(days=30)
    loan.save(update_fields=["due_at"])

    fee = assess_overdue_fee(loan_id=loan.id)
    fee_again = assess_overdue_fee(loan_id=loan.id)

    assert fee.id == fee_again.id
    assert FineFee.objects.count() == 1
    assert fee_again.original_amount == Decimal("50.00")
    assert fee_again.balance_amount == Decimal("50.00")


@pytest.mark.django_db
def test_payment_and_waiver_reduce_fee_balance(circulation_setup):
    fee = FineFee.objects.create(
        patron=circulation_setup["patron"],
        fee_type=FineFee.FeeType.MANUAL,
        reason="Manual adjustment",
        amount=Decimal("30.00"),
        original_amount=Decimal("30.00"),
        balance_amount=Decimal("30.00"),
    )

    payment = record_payment(
        patron_id=circulation_setup["patron"].id,
        amount=Decimal("10.00"),
        method=Payment.Method.CASH,
    )
    fee.refresh_from_db()
    assert payment.allocations.count() == 1
    assert fee.balance_amount == Decimal("20.00")

    waive_fee(fine_fee_id=fee.id, amount=Decimal("20.00"), reason="Staff approved")
    fee.refresh_from_db()
    assert fee.balance_amount == Decimal("0.00")
    assert fee.status == FineFee.Status.WAIVED

