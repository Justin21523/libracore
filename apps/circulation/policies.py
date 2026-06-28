from __future__ import annotations

from django.utils import timezone

from apps.circulation.models import BranchCalendarException, CirculationPolicy, Patron
from apps.holdings.models import Item


def resolve_policy(patron: Patron, item: Item) -> CirculationPolicy:
    instance = item.holding.instance
    candidates = CirculationPolicy.objects.filter(is_active=True).order_by("priority", "created_at")
    for policy in candidates:
        if policy.patron_type and policy.patron_type != patron.patron_type:
            continue
        if policy.branch_id and policy.branch_id != item.holding.branch_id:
            continue
        if policy.location_id and policy.location_id != item.holding.location_id:
            continue
        if policy.resource_type and policy.resource_type != instance.resource_type:
            continue
        return policy
    return CirculationPolicy.objects.create(
        name="Default circulation policy",
        priority=9999,
        loan_period_days=14,
        renewal_period_days=14,
        max_renewals=2,
        max_open_loans=20,
        max_holds=10,
        allow_holds=True,
        allow_renewal_when_holds=False,
        hold_shelf_days=7,
    )


def next_open_due_at(start_at, branch, days: int):
    due_at = start_at + timezone.timedelta(days=days)
    while BranchCalendarException.objects.filter(
        branch=branch,
        date=timezone.localtime(due_at).date(),
        is_closed=True,
    ).exists():
        due_at += timezone.timedelta(days=1)
    return due_at

