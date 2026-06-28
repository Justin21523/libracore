from django.http import FileResponse
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.permissions import AdminRolePermission

from .models import ExportJob
from .serializers import ExportJobCreateSerializer, ExportJobSerializer
from .services import create_and_run_export_job, export_content_type


class ExportJobViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = ExportJob.objects.select_related("requested_by").all()
    permission_classes = [AdminRolePermission]
    serializer_class = ExportJobSerializer
    search_fields = ["export_type", "status", "requested_by__username"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        if self.action == "create":
            return ExportJobCreateSerializer
        return ExportJobSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        job = create_and_run_export_job(
            export_type=serializer.validated_data["export_type"],
            requested_by=request.user,
            parameters=serializer.validated_data.get("parameters") or {},
        )
        response_serializer = ExportJobSerializer(job, context=self.get_serializer_context())
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        job = self.get_object()
        if job.status != ExportJob.Status.COMPLETED or not job.result_file:
            return Response(
                {"detail": "Export file is not available."},
                status=status.HTTP_409_CONFLICT,
            )
        return FileResponse(
            job.result_file.open("rb"),
            as_attachment=True,
            filename=job.result_file.name.rsplit("/", 1)[-1],
            content_type=export_content_type(job),
        )


def register(router):
    router.register("export-jobs", ExportJobViewSet, basename="export-job")
