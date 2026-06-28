from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from apps.acquisitions.models import Vendor
from apps.catalog.models import Instance, Work
from apps.circulation.models import FineFee, HoldRequest, Loan, Patron
from apps.erm.models import License
from apps.holdings.models import Branch, Holding, Item, Location
from apps.notifications.models import Notification, NotificationTemplate
from apps.notifications.services import generate_notifications, send_pending_notifications


@pytest.fixture
def notification_setup():
    branch = Branch.objects.create(code="notify-main", name="通知總館")
    location = Location.objects.create(branch=branch, code="open", name="開架")
    work = Work.objects.create(primary_title="通知測試")
    instance = Instance.objects.create(work=work, title_statement="通知測試")
    holding = Holding.objects.create(instance=instance, branch=branch, location=location)
    item = Item.objects.create(holding=holding, barcode="NOTIFY-I001", status=Item.Status.ON_LOAN)
    user = get_user_model().objects.create_user(
        username="notify-reader",
        password="x",
        email="notify@example.test",
    )
    patron = Patron.objects.create(user=user, barcode="NOTIFY-P001", home_branch=branch)
    loan = Loan.objects.create(
        item=item,
        patron=patron,
        due_at=timezone.now() + timezone.timedelta(days=1),
    )
    ready_hold = HoldRequest.objects.create(
        patron=patron,
        instance=instance,
        item=item,
        pickup_location=location,
        status=HoldRequest.Status.READY,
        expires_at=timezone.now() + timezone.timedelta(days=5),
    )
    fee = FineFee.objects.create(
        patron=patron,
        loan=loan,
        reason="Overdue item",
        amount=Decimal("15.00"),
        original_amount=Decimal("15.00"),
        balance_amount=Decimal("15.00"),
    )
    staff = get_user_model().objects.create_user(
        username="notify-staff",
        password="x",
        email="staff@example.test",
        is_staff=True,
    )
    vendor = Vendor.objects.create(code="notify-vendor", name="Notify Vendor")
    license_obj = License.objects.create(
        name="Notify License",
        vendor=vendor,
        status=License.Status.ACTIVE,
        ends_at=timezone.localdate() + timezone.timedelta(days=10),
        renewal_notice_days=30,
    )
    return {
        "user": user,
        "patron": patron,
        "loan": loan,
        "ready_hold": ready_hold,
        "fee": fee,
        "staff": staff,
        "license": license_obj,
    }


@pytest.mark.django_db
def test_generate_notifications_creates_all_types_and_is_idempotent(notification_setup):
    notification_setup["loan"].due_at = timezone.now() - timezone.timedelta(days=1)
    notification_setup["loan"].save(update_fields=["due_at"])

    first = generate_notifications()
    second = generate_notifications()

    assert first["overdue"]["created"] >= 2
    assert first["hold_available"]["created"] >= 2
    assert first["fine_notice"]["created"] >= 2
    assert first["license_expiry_staff"]["created"] >= 2
    assert second["overdue"]["skipped"] >= 2
    assert Notification.objects.filter(
        notification_type=NotificationTemplate.NotificationType.OVERDUE
    ).exists()


@pytest.mark.django_db
def test_due_soon_generation_and_send_pending_email(notification_setup):
    generate_notifications(notification_type=NotificationTemplate.NotificationType.DUE_SOON)

    assert Notification.objects.filter(
        notification_type=NotificationTemplate.NotificationType.DUE_SOON,
        channel=NotificationTemplate.Channel.EMAIL,
        status=Notification.Status.PENDING,
    ).exists()

    result = send_pending_notifications()

    assert result["sent"] >= 1
    assert Notification.objects.filter(
        channel=NotificationTemplate.Channel.EMAIL, status=Notification.Status.SENT
    ).exists()


@pytest.mark.django_db
def test_notification_api_scopes_reader_and_allows_mark_read(notification_setup):
    generate_notifications(notification_type=NotificationTemplate.NotificationType.DUE_SOON)
    notification = Notification.objects.filter(
        recipient_user=notification_setup["user"], channel="in_app"
    ).first()
    client = APIClient()

    assert client.get("/api/notifications/").status_code == 403

    client.force_authenticate(notification_setup["user"])
    own = client.get("/api/notifications/")
    read = client.post(f"/api/notifications/{notification.id}/mark-read/")
    generate_denied = client.post("/api/notifications/generate/", {})

    notification.refresh_from_db()
    assert own.status_code == 200
    assert read.status_code == 200
    assert notification.status == Notification.Status.READ
    assert generate_denied.status_code == 403


@pytest.mark.django_db
def test_staff_can_generate_notifications_via_api(notification_setup):
    client = APIClient()
    client.force_authenticate(notification_setup["staff"])

    response = client.post("/api/notifications/generate/", {"type": "due_soon"}, format="json")

    assert response.status_code == 200
    assert response.data["due_soon"]["created"] >= 2


@pytest.mark.django_db
def test_notification_management_commands(notification_setup):
    call_command("generate_notifications", "--type", "due_soon")
    call_command("send_notifications")

    assert Notification.objects.filter(
        notification_type=NotificationTemplate.NotificationType.DUE_SOON
    ).exists()
