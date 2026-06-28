from __future__ import annotations

from functools import wraps

from django.core.exceptions import PermissionDenied
from rest_framework import permissions

from .roles import (
    ROLE_ACQUISITIONS,
    ROLE_ADMIN,
    ROLE_CATALOGER,
    ROLE_CIRCULATION,
    ROLE_ERM,
    ROLE_REPOSITORY,
    user_has_role,
)


def role_required(*roles: str):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not user_has_role(request.user, *roles):
                raise PermissionDenied("Required staff role is missing.")
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator


class StaffRolePermission(permissions.BasePermission):
    required_roles: tuple[str, ...] = ()
    safe_methods_allow_read = True

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS and self.safe_methods_allow_read:
            return bool(request.user and request.user.is_authenticated and request.user.is_staff)
        return user_has_role(request.user, *self.required_roles)


class AdminRolePermission(StaffRolePermission):
    required_roles = (ROLE_ADMIN,)
    safe_methods_allow_read = False


class CatalogerRolePermission(StaffRolePermission):
    required_roles = (ROLE_CATALOGER,)


class CirculationRolePermission(StaffRolePermission):
    required_roles = (ROLE_CIRCULATION,)


class AcquisitionsRolePermission(StaffRolePermission):
    required_roles = (ROLE_ACQUISITIONS,)


class ErmRolePermission(StaffRolePermission):
    required_roles = (ROLE_ERM,)


class RepositoryRolePermission(StaffRolePermission):
    required_roles = (ROLE_REPOSITORY,)


class PublicReadRoleWritePermission(permissions.BasePermission):
    required_roles: tuple[str, ...] = ()

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return user_has_role(request.user, *self.required_roles)


class PublicReadCatalogerWritePermission(PublicReadRoleWritePermission):
    required_roles = (ROLE_CATALOGER,)
