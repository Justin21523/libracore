from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.core.api import BaseModelViewSet
from apps.core.permissions import PublicReadCatalogerWritePermission
from apps.core.roles import ROLE_CATALOGER, user_has_role
from apps.marc.mapping import map_record
from apps.marc.parser import parse_iso2709, validate_parsed_record

from .models import (
    AuthorityLinkSuggestion,
    MarcImportBatch,
    MarcImportRecord,
    MarcMatchCandidate,
    MarcRecord,
)
from .review_services import (
    ActorContext,
    CatalogingError,
    accept_authority_suggestion,
    approve_import_record,
    create_import_batch,
    create_provisional_authority_from_suggestion,
    parse_import_batch,
    reject_authority_suggestion,
    reject_import_record,
    resolve_import_record,
)
from .serializers import (
    AuthorityLinkSuggestionSerializer,
    AuthoritySuggestionAcceptSerializer,
    MarcApproveSerializer,
    MarcImportBatchCreateSerializer,
    MarcImportBatchSerializer,
    MarcImportRecordSerializer,
    MarcMatchCandidateSerializer,
    MarcRecordSerializer,
    MarcRejectSerializer,
    MarcResolveSerializer,
)


def _require_staff(request):
    if not user_has_role(request.user, ROLE_CATALOGER):
        raise PermissionDenied("Cataloger permission is required.")


def _actor_context(request) -> ActorContext:
    return ActorContext(
        actor=request.user,
        ip_address=request.META.get("REMOTE_ADDR"),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )


def _error_response(exc: CatalogingError):
    return Response({"code": exc.code, "detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class MarcRecordViewSet(BaseModelViewSet):
    queryset = MarcRecord.objects.select_related("bibliographic_record", "authority_record").all()
    serializer_class = MarcRecordSerializer
    permission_classes = [PublicReadCatalogerWritePermission]
    search_fields = ["control_number", "source", "leader"]
    ordering_fields = ["format_type", "validation_status", "created_at", "updated_at"]

    @action(detail=False, methods=["post"], url_path="parse")
    def parse(self, request):
        raw = request.data.get("raw", "")
        parsed = parse_iso2709(raw)
        return Response(
            {
                "parsed": parsed,
                "validation_errors": validate_parsed_record(parsed),
                "mapping": map_record(parsed),
            }
        )


class MarcImportBatchViewSet(BaseModelViewSet):
    queryset = MarcImportBatch.objects.select_related("submitted_by").all()
    serializer_class = MarcImportBatchSerializer
    permission_classes = [PublicReadCatalogerWritePermission]
    search_fields = ["source", "filename", "notes"]
    ordering_fields = ["status", "created_at", "completed_at"]

    def create(self, request, *args, **kwargs):
        _require_staff(request)
        serializer = MarcImportBatchCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            batch = create_import_batch(
                payload=serializer.validated_data["payload"],
                import_format=serializer.validated_data["import_format"],
                source=serializer.validated_data.get("source", ""),
                filename=serializer.validated_data.get("filename", ""),
                actor_context=_actor_context(request),
            )
        except ValueError as exc:
            return Response(
                {"code": "invalid_import_payload", "detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(self.get_serializer(batch).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def parse(self, request, pk=None):
        _require_staff(request)
        try:
            batch = parse_import_batch(batch_id=pk, actor_context=_actor_context(request))
        except CatalogingError as exc:
            return _error_response(exc)
        return Response(self.get_serializer(batch).data)


class MarcImportRecordViewSet(BaseModelViewSet):
    queryset = MarcImportRecord.objects.select_related(
        "batch", "marc_record", "bibliographic_record"
    ).all()
    serializer_class = MarcImportRecordSerializer
    permission_classes = [PublicReadCatalogerWritePermission]
    search_fields = ["control_number", "conflict_reason", "batch__filename"]
    ordering_fields = ["sequence", "status", "created_at"]

    def get_queryset(self):
        queryset = super().get_queryset()
        batch_id = self.request.query_params.get("batch")
        status_value = self.request.query_params.get("status")
        if batch_id:
            queryset = queryset.filter(batch_id=batch_id)
        if status_value:
            queryset = queryset.filter(status=status_value)
        return queryset

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        record = self.get_object()
        return Response(
            {
                "parsed": record.parsed_json,
                "mapped": record.mapped_json,
                "format_type": record.format_type,
                "validation_errors": record.validation_errors,
                "conflict_reason": record.conflict_reason,
                "match_candidates": MarcMatchCandidateSerializer(
                    record.match_candidates.all(), many=True
                ).data,
                "resolution_actions": ["create_new", "link_existing", "overlay_existing"],
            }
        )

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        _require_staff(request)
        serializer = MarcApproveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            record = approve_import_record(
                import_record_id=pk,
                mapped_overrides=serializer.validated_data.get("mapped_overrides", {}),
                actor_context=_actor_context(request),
            )
        except CatalogingError as exc:
            return _error_response(exc)
        return Response(self.get_serializer(record).data)

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        _require_staff(request)
        serializer = MarcResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            record = resolve_import_record(
                import_record_id=pk,
                action=serializer.validated_data["action"],
                target_id=serializer.validated_data.get("target_id") or None,
                mapped_overrides=serializer.validated_data.get("mapped_overrides", {}),
                actor_context=_actor_context(request),
            )
        except CatalogingError as exc:
            return _error_response(exc)
        return Response(self.get_serializer(record).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        _require_staff(request)
        serializer = MarcRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            record = reject_import_record(
                import_record_id=pk,
                note=serializer.validated_data.get("note", ""),
                actor_context=_actor_context(request),
            )
        except CatalogingError as exc:
            return _error_response(exc)
        return Response(self.get_serializer(record).data)


class MarcMatchCandidateViewSet(BaseModelViewSet):
    queryset = MarcMatchCandidate.objects.select_related("import_record").all()
    serializer_class = MarcMatchCandidateSerializer
    permission_classes = [PublicReadCatalogerWritePermission]
    search_fields = ["target_type", "target_id", "match_rule", "reason"]
    ordering_fields = ["confidence", "created_at"]

    def get_queryset(self):
        queryset = super().get_queryset()
        import_record_id = self.request.query_params.get("import_record")
        if import_record_id:
            queryset = queryset.filter(import_record_id=import_record_id)
        return queryset


class AuthorityLinkSuggestionViewSet(BaseModelViewSet):
    queryset = AuthorityLinkSuggestion.objects.select_related(
        "import_record", "matched_authority"
    ).all()
    serializer_class = AuthorityLinkSuggestionSerializer
    permission_classes = [PublicReadCatalogerWritePermission]
    search_fields = ["label", "marc_tag", "authority_type", "role"]
    ordering_fields = ["status", "confidence", "created_at"]

    def get_queryset(self):
        queryset = super().get_queryset()
        import_record_id = self.request.query_params.get("import_record")
        if import_record_id:
            queryset = queryset.filter(import_record_id=import_record_id)
        return queryset

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        _require_staff(request)
        serializer = AuthoritySuggestionAcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            suggestion = accept_authority_suggestion(
                suggestion_id=pk,
                authority_id=serializer.validated_data["authority_id"],
                actor_context=_actor_context(request),
            )
        except CatalogingError as exc:
            return _error_response(exc)
        return Response(self.get_serializer(suggestion).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        _require_staff(request)
        note = request.data.get("note", "")
        suggestion = reject_authority_suggestion(
            suggestion_id=pk,
            note=note,
            actor_context=_actor_context(request),
        )
        return Response(self.get_serializer(suggestion).data)

    @action(detail=True, methods=["post"], url_path="create-provisional-authority")
    def create_provisional_authority(self, request, pk=None):
        _require_staff(request)
        suggestion = create_provisional_authority_from_suggestion(
            suggestion_id=pk,
            actor_context=_actor_context(request),
        )
        return Response(self.get_serializer(suggestion).data, status=status.HTTP_201_CREATED)


def register(router):
    router.register("marc-records", MarcRecordViewSet, basename="marc-record")
    router.register("marc-import-batches", MarcImportBatchViewSet, basename="marc-import-batch")
    router.register("marc-import-records", MarcImportRecordViewSet, basename="marc-import-record")
    router.register(
        "marc-match-candidates", MarcMatchCandidateViewSet, basename="marc-match-candidate"
    )
    router.register(
        "authority-link-suggestions",
        AuthorityLinkSuggestionViewSet,
        basename="authority-link-suggestion",
    )
