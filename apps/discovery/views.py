from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.catalog.models import Instance
from apps.circulation.models import FineFee, HoldRequest, Loan, Patron
from apps.circulation.services import (
    ActorContext,
    CirculationError,
    cancel_hold,
    place_hold,
    renew_loan,
)
from apps.discovery.search import search_documents
from apps.erm.services import (
    public_access_links,
    public_resources_for_instance,
    resource_coverage_statements,
)
from apps.holdings.models import Location
from apps.notifications.models import Notification
from apps.notifications.services import mark_notification_read
from apps.repository.models import DigitalObject
from apps.repository.services import public_file_assets


def search_home(request):
    return render(request, "opac/search_home.html")


def search_results(request):
    query = request.GET.get("q", "")
    filters = _filters_from_request(request)
    page = int(request.GET.get("page", "1") or 1)
    result_page = search_documents(query=query, filters=filters, page=page)
    template = (
        "opac/partials/search_results.html"
        if request.headers.get("HX-Request")
        else "opac/search_results.html"
    )
    return render(request, template, {"result_page": result_page})


def record_detail(request, instance_id):
    instance = get_object_or_404(
        Instance.objects.select_related("work", "expression").prefetch_related(
            "holdings__branch",
            "holdings__location",
            "holdings__items",
            "bib_records",
        ),
        id=instance_id,
    )
    online_resources = [
        {
            "resource": resource,
            "access_links": public_access_links(resource),
            "coverage_statements": resource_coverage_statements(resource),
        }
        for resource in public_resources_for_instance(instance)
    ]
    digital_objects = [
        {"object": obj, "public_files": public_file_assets(obj)}
        for obj in DigitalObject.objects.filter(
            bibliographic_record__instance=instance,
            status=DigitalObject.Status.PUBLISHED,
        ).prefetch_related("file_assets")
    ]
    return render(
        request,
        "opac/record_detail.html",
        {
            "instance": instance,
            "online_resources": online_resources,
            "digital_objects": digital_objects,
            "patron_context": _patron_context(request, instance),
        },
    )


def record_availability(request, instance_id):
    instance = get_object_or_404(
        Instance.objects.prefetch_related(
            "holdings__branch", "holdings__location", "holdings__items"
        ),
        id=instance_id,
    )
    return render(
        request,
        "opac/partials/availability.html",
        {"instance": instance, "patron_context": _patron_context(request, instance)},
    )


@login_required
def account_dashboard(request):
    patron = _patron_for_user(request.user)
    if not patron:
        return render(request, "opac/account/dashboard.html", {"patron": None})
    open_loans = _patron_loans(patron).filter(status=Loan.Status.OPEN)
    active_holds = _patron_holds(patron).filter(
        status__in=[HoldRequest.Status.QUEUED, HoldRequest.Status.READY]
    )
    open_fees = _patron_fees(patron).filter(status=FineFee.Status.OPEN)
    unread_notifications = Notification.objects.filter(
        recipient_user=request.user,
        status__in=[Notification.Status.SENT, Notification.Status.PENDING],
        channel="in_app",
    )
    return render(
        request,
        "opac/account/dashboard.html",
        {
            "patron": patron,
            "open_loans": open_loans,
            "active_holds": active_holds,
            "open_fees": open_fees,
            "unread_notifications": unread_notifications,
        },
    )


@login_required
def account_loans(request):
    patron = _patron_for_user(request.user)
    loans = _patron_loans(patron) if patron else Loan.objects.none()
    return render(request, "opac/account/loans.html", {"patron": patron, "loans": loans})


@login_required
def account_holds(request):
    patron = _patron_for_user(request.user)
    holds = _patron_holds(patron) if patron else HoldRequest.objects.none()
    return render(request, "opac/account/holds.html", {"patron": patron, "holds": holds})


@login_required
def account_fees(request):
    patron = _patron_for_user(request.user)
    fees = _patron_fees(patron) if patron else FineFee.objects.none()
    return render(request, "opac/account/fees.html", {"patron": patron, "fees": fees})


@login_required
def account_notifications(request):
    notifications = Notification.objects.filter(recipient_user=request.user, channel="in_app")
    return render(request, "opac/account/notifications.html", {"notifications": notifications})


@login_required
def account_notification_mark_read(request, notification_id):
    notification = get_object_or_404(Notification, id=notification_id, recipient_user=request.user)
    mark_notification_read(notification)
    return redirect("discovery:account_notifications")


@login_required
def account_renew_loan(request, loan_id):
    patron = _patron_for_user(request.user)
    loan = get_object_or_404(Loan, id=loan_id, patron=patron)
    try:
        renew_loan(loan_id=loan.id, actor_context=_actor_context(request))
        messages.success(request, "續借完成。")
    except CirculationError as exc:
        messages.error(request, str(exc))
    return redirect("discovery:account_loans")


@login_required
def account_cancel_hold(request, hold_id):
    patron = _patron_for_user(request.user)
    hold = get_object_or_404(HoldRequest, id=hold_id, patron=patron)
    try:
        cancel_hold(hold_id=hold.id, actor_context=_actor_context(request))
        messages.success(request, "預約已取消。")
    except CirculationError as exc:
        messages.error(request, str(exc))
    return redirect("discovery:account_holds")


@login_required
def record_place_hold(request, instance_id):
    instance = get_object_or_404(Instance, id=instance_id)
    patron = _patron_for_user(request.user)
    pickup_location = _pickup_location_for_patron(patron)
    if not patron:
        messages.error(request, "尚未建立讀者檔，無法預約。")
        return redirect("discovery:record_detail", instance_id=instance.id)
    if not pickup_location:
        messages.error(request, "找不到可用的取書館藏地。")
        return redirect("discovery:record_detail", instance_id=instance.id)
    try:
        place_hold(
            patron_id=patron.id,
            instance_id=instance.id,
            pickup_location_id=pickup_location.id,
            actor_context=_actor_context(request),
        )
        messages.success(request, "預約已建立。")
    except CirculationError as exc:
        messages.error(request, str(exc))
    return redirect("discovery:record_detail", instance_id=instance.id)


def _filters_from_request(request) -> dict:
    keys = [
        "resource_type",
        "availability",
        "branch",
        "location",
        "language",
        "year",
        "online_available",
        "platform",
        "resource_mode",
        "repository_available",
        "file_mime_type",
    ]
    return {key: request.GET.get(key) for key in keys if request.GET.get(key)}


def _patron_for_user(user):
    if not user.is_authenticated:
        return None
    try:
        return user.patron
    except Patron.DoesNotExist:
        return None


def _patron_loans(patron):
    return (
        Loan.objects.filter(patron=patron)
        .select_related("item__holding__instance")
        .order_by("-checked_out_at")
    )


def _patron_holds(patron):
    return (
        HoldRequest.objects.filter(patron=patron)
        .select_related("instance", "item__holding__instance", "pickup_location")
        .order_by("-created_at")
    )


def _patron_fees(patron):
    return (
        FineFee.objects.filter(patron=patron)
        .select_related("loan__item__holding__instance")
        .order_by("-created_at")
    )


def _pickup_location_for_patron(patron):
    if not patron:
        return None
    if patron.home_branch_id:
        location = Location.objects.filter(branch=patron.home_branch, is_public=True).first()
        if location:
            return location
    return Location.objects.filter(is_public=True).first()


def _patron_context(request, instance=None):
    patron = _patron_for_user(request.user)
    has_holdings = bool(instance and instance.holdings.exists())
    return {
        "patron": patron,
        "can_place_hold": bool(patron and has_holdings and _pickup_location_for_patron(patron)),
        "has_holdings": has_holdings,
        "pickup_location": _pickup_location_for_patron(patron) if patron else None,
    }


def _actor_context(request) -> ActorContext:
    return ActorContext(
        actor=request.user,
        ip_address=request.META.get("REMOTE_ADDR"),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )
