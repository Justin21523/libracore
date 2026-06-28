import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.catalog.models import Instance, Work
from apps.circulation.models import Loan, Patron
from apps.holdings.models import Branch, Holding, Item, Location


@pytest.mark.django_db
def test_work_instance_item_loan_are_separate_layers():
    work = Work.objects.create(primary_title="紅樓夢")
    instance = Instance.objects.create(work=work, title_statement="紅樓夢", publisher="某出版社")
    branch = Branch.objects.create(code="main", name="總館")
    location = Location.objects.create(branch=branch, code="stack", name="書庫")
    holding = Holding.objects.create(instance=instance, branch=branch, location=location)
    item = Item.objects.create(holding=holding, barcode="BC001", status=Item.Status.AVAILABLE)
    user = get_user_model().objects.create_user(username="reader")
    patron = Patron.objects.create(user=user, barcode="P001", home_branch=branch)
    loan = Loan.objects.create(
        item=item,
        patron=patron,
        due_at=timezone.now() + timezone.timedelta(days=14),
    )

    assert item.holding.instance.work == work
    assert loan.item.barcode == "BC001"
    assert loan.patron.barcode == "P001"

