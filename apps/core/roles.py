from __future__ import annotations

from django.contrib.auth.models import Group

ROLE_CATALOGER = "cataloger"
ROLE_CIRCULATION = "circulation_staff"
ROLE_ACQUISITIONS = "acquisitions_staff"
ROLE_ERM = "erm_staff"
ROLE_REPOSITORY = "repository_staff"
ROLE_ADMIN = "admin"

ROLE_LABELS = {
    ROLE_CATALOGER: "Cataloger",
    ROLE_CIRCULATION: "Circulation staff",
    ROLE_ACQUISITIONS: "Acquisitions staff",
    ROLE_ERM: "ERM staff",
    ROLE_REPOSITORY: "Repository staff",
    ROLE_ADMIN: "System administrator",
}


def seed_role_groups() -> list[Group]:
    groups = []
    for role in ROLE_LABELS:
        group, _ = Group.objects.get_or_create(name=role)
        groups.append(group)
    return groups


def user_has_role(user, *roles: str) -> bool:
    if not user or not user.is_authenticated or not user.is_staff:
        return False
    if not Group.objects.filter(name__in=ROLE_LABELS.keys()).exists():
        return True
    if user.is_superuser:
        return True
    if user.groups.filter(name=ROLE_ADMIN).exists():
        return True
    if not roles:
        return user.is_staff
    return user.groups.filter(name__in=roles).exists()


def user_is_admin(user) -> bool:
    return user_has_role(user, ROLE_ADMIN)
