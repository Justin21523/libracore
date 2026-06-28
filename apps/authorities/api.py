from rest_framework import permissions, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.catalog.models import BibliographicRecord, InstanceContributor, WorkAuthorityLink
from apps.core.api import BaseModelViewSet
from apps.core.roles import ROLE_ADMIN, ROLE_CATALOGER, user_has_role

from .models import AccessPoint, AuthorityRecord, AuthorityRelation, ExternalIdentifier
from .serializers import (
    AccessPointInputSerializer,
    AccessPointSerializer,
    AuthorityCreateSerializer,
    AuthorityDeprecateSerializer,
    AuthorityMergeSerializer,
    AuthorityRecordSerializer,
    AuthorityRelationInputSerializer,
    AuthorityRelationSerializer,
    ExternalIdentifierSerializer,
    SetPreferredSerializer,
)
from .services import (
    ActorContext,
    AuthorityError,
    add_access_point,
    add_authority_relation,
    create_authority,
    deprecate_authority,
    merge_authorities,
    set_preferred_access_point,
)


def _require_staff(request):
    if not user_has_role(request.user, ROLE_CATALOGER):
        raise PermissionDenied("Cataloger permission is required.")


def _require_admin(request):
    if not user_has_role(request.user, ROLE_ADMIN):
        raise PermissionDenied("Admin permission is required.")


class CatalogerWritePermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return user_has_role(request.user, ROLE_CATALOGER)


def _actor_context(request) -> ActorContext:
    return ActorContext(
        actor=request.user,
        ip_address=request.META.get("REMOTE_ADDR"),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )


def _error_response(exc: AuthorityError):
    return Response({"code": exc.code, "detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class AuthorityRecordViewSet(BaseModelViewSet):
    queryset = AuthorityRecord.objects.prefetch_related("access_points").all()
    serializer_class = AuthorityRecordSerializer
    permission_classes = [CatalogerWritePermission]
    search_fields = ["control_number", "entity_uri", "access_points__label"]
    ordering_fields = ["authority_type", "status", "created_at", "updated_at"]

    def create(self, request, *args, **kwargs):
        _require_staff(request)
        serializer = AuthorityCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        authority = create_authority(
            **serializer.validated_data, actor_context=_actor_context(request)
        )
        return Response(self.get_serializer(authority).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"])
    def browse(self, request):
        queryset = self.get_queryset()
        if request.query_params.get("q"):
            queryset = queryset.filter(access_points__label__icontains=request.query_params["q"])
        if request.query_params.get("authority_type"):
            queryset = queryset.filter(authority_type=request.query_params["authority_type"])
        if request.query_params.get("status"):
            queryset = queryset.filter(status=request.query_params["status"])
        queryset = queryset.distinct().order_by("access_points__sort_key", "created_at")[:100]
        return Response(self.get_serializer(queryset, many=True).data)

    @action(detail=True, methods=["get"], url_path="linked-records")
    def linked_records(self, request, pk=None):
        authority = self.get_object()
        work_ids = WorkAuthorityLink.objects.filter(authority=authority).values_list(
            "work_id", flat=True
        )
        instance_ids = InstanceContributor.objects.filter(authority=authority).values_list(
            "instance_id", flat=True
        )
        records = BibliographicRecord.objects.filter(
            work_id__in=work_ids
        ) | BibliographicRecord.objects.filter(instance_id__in=instance_ids)
        return Response(
            [
                {
                    "id": str(record.id),
                    "control_number": record.control_number,
                    "title": record.instance.title_statement if record.instance_id else "",
                    "instance_id": str(record.instance_id) if record.instance_id else "",
                }
                for record in records.select_related("instance").distinct()
            ]
        )

    @action(detail=True, methods=["post"], url_path="set-preferred-access-point")
    def set_preferred(self, request, pk=None):
        _require_staff(request)
        serializer = SetPreferredSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            access_point = set_preferred_access_point(
                authority_id=pk,
                access_point_id=serializer.validated_data["access_point_id"],
                actor_context=_actor_context(request),
            )
        except AuthorityError as exc:
            return _error_response(exc)
        return Response(AccessPointSerializer(access_point).data)

    @action(detail=True, methods=["post"], url_path="add-variant")
    def add_variant(self, request, pk=None):
        _require_staff(request)
        serializer = AccessPointInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            access_point = add_access_point(
                authority_id=pk, **serializer.validated_data, actor_context=_actor_context(request)
            )
        except AuthorityError as exc:
            return _error_response(exc)
        return Response(AccessPointSerializer(access_point).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="add-relation")
    def add_relation(self, request, pk=None):
        _require_staff(request)
        serializer = AuthorityRelationInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            relation = add_authority_relation(
                source_id=pk,
                target_id=serializer.validated_data["target_id"],
                relation_type=serializer.validated_data["relation_type"],
                note=serializer.validated_data.get("note", ""),
                actor_context=_actor_context(request),
            )
        except AuthorityError as exc:
            return _error_response(exc)
        return Response(AuthorityRelationSerializer(relation).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def deprecate(self, request, pk=None):
        _require_admin(request)
        serializer = AuthorityDeprecateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            authority = deprecate_authority(
                authority_id=pk,
                replacement_id=serializer.validated_data.get("replacement_id"),
                note=serializer.validated_data.get("note", ""),
                actor_context=_actor_context(request),
            )
        except AuthorityError as exc:
            return _error_response(exc)
        return Response(self.get_serializer(authority).data)

    @action(detail=True, methods=["post"])
    def merge(self, request, pk=None):
        _require_admin(request)
        serializer = AuthorityMergeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            target = merge_authorities(
                source_id=pk,
                target_id=serializer.validated_data["target_id"],
                note=serializer.validated_data.get("note", ""),
                actor_context=_actor_context(request),
            )
        except AuthorityError as exc:
            return _error_response(exc)
        return Response(self.get_serializer(target).data)


class AccessPointViewSet(BaseModelViewSet):
    queryset = AccessPoint.objects.select_related("authority").all()
    serializer_class = AccessPointSerializer
    permission_classes = [CatalogerWritePermission]
    search_fields = ["label", "romanization"]
    ordering_fields = ["label", "kind", "created_at"]


class AuthorityRelationViewSet(BaseModelViewSet):
    queryset = AuthorityRelation.objects.select_related("source", "target").all()
    serializer_class = AuthorityRelationSerializer
    permission_classes = [CatalogerWritePermission]


class ExternalIdentifierViewSet(BaseModelViewSet):
    queryset = ExternalIdentifier.objects.select_related("authority").all()
    serializer_class = ExternalIdentifierSerializer
    permission_classes = [CatalogerWritePermission]
    search_fields = ["scheme", "value", "uri"]


def register(router):
    router.register("authorities", AuthorityRecordViewSet, basename="authority")
    router.register(
        "authority-access-points", AccessPointViewSet, basename="authority-access-point"
    )
    router.register("authority-relations", AuthorityRelationViewSet, basename="authority-relation")
    router.register(
        "authority-identifiers", ExternalIdentifierViewSet, basename="authority-identifier"
    )
