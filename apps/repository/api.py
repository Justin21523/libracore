from rest_framework import permissions, status
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.core.api import BaseModelViewSet
from apps.core.roles import ROLE_REPOSITORY, user_has_role

from .models import DigitalObject, FileAsset
from .serializers import DigitalObjectSerializer, FileAssetSerializer
from .services import enrich_uploaded_asset, publish_object, withdraw_object


class RepositoryPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return user_has_role(request.user, ROLE_REPOSITORY)


class DigitalObjectViewSet(BaseModelViewSet):
    serializer_class = DigitalObjectSerializer
    permission_classes = [RepositoryPermission]
    search_fields = ["title", "oai_identifier", "rights_statement"]

    def get_queryset(self):
        queryset = (
            DigitalObject.objects.select_related("bibliographic_record")
            .prefetch_related("file_assets")
            .all()
        )
        if self.request.user.is_authenticated and self.request.user.is_staff:
            return queryset
        return queryset.filter(status=DigitalObject.Status.PUBLISHED)

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        obj = publish_object(self.get_object(), **_actor_kwargs(request))
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        obj = withdraw_object(self.get_object(), **_actor_kwargs(request))
        return Response(self.get_serializer(obj).data)

    @action(
        detail=True,
        methods=["post"],
        parser_classes=[MultiPartParser, FormParser],
        url_path="files",
    )
    def files(self, request, pk=None):
        obj = self.get_object()
        if "file" not in request.FILES:
            return Response(
                {"file": ["This field is required."]}, status=status.HTTP_400_BAD_REQUEST
            )
        asset = FileAsset.objects.create(
            digital_object=obj,
            file=request.FILES["file"],
            label=request.data.get("label", ""),
            access_level=request.data.get("access_level", "public"),
            mime_type=request.data.get("mime_type", ""),
            ocr_text=request.data.get("ocr_text", ""),
        )
        enrich_uploaded_asset(asset, **_actor_kwargs(request))
        return Response(
            FileAssetSerializer(asset, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )


class FileAssetViewSet(BaseModelViewSet):
    serializer_class = FileAssetSerializer
    permission_classes = [RepositoryPermission]
    search_fields = ["label", "mime_type", "checksum_sha256", "ocr_text"]

    def get_queryset(self):
        queryset = FileAsset.objects.select_related("digital_object").all()
        if self.request.user.is_authenticated and self.request.user.is_staff:
            return queryset
        return queryset.filter(
            digital_object__status=DigitalObject.Status.PUBLISHED,
            access_level="public",
        )

    def perform_create(self, serializer):
        asset = serializer.save()
        enrich_uploaded_asset(asset, **_actor_kwargs(self.request))


def register(router):
    router.register("digital-objects", DigitalObjectViewSet, basename="digital-object")
    router.register("file-assets", FileAssetViewSet, basename="file-asset")


def _actor_kwargs(request):
    return {
        "actor": request.user,
        "ip_address": request.META.get("REMOTE_ADDR"),
        "user_agent": request.META.get("HTTP_USER_AGENT", ""),
    }
