from django.http import FileResponse
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import ReportDefinition, ReportRun
from .services import (
    ReportPermissionError,
    can_run_report,
    run_report,
    visible_report_codes,
    visible_report_definitions,
)


class ReportDefinitionSerializer(serializers.ModelSerializer):
    can_run = serializers.SerializerMethodField()

    class Meta:
        model = ReportDefinition
        fields = [
            "id",
            "code",
            "name",
            "description",
            "query_spec",
            "required_permission",
            "can_run",
            "created_at",
            "updated_at",
        ]

    def get_can_run(self, obj):
        request = self.context.get("request")
        return bool(request and can_run_report(request.user, obj.code))


class ReportRunSerializer(serializers.ModelSerializer):
    requested_by_username = serializers.CharField(source="requested_by.username", read_only=True)
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = ReportRun
        fields = [
            "id",
            "report_definition",
            "code",
            "name",
            "status",
            "requested_by",
            "requested_by_username",
            "parameters",
            "result_json",
            "record_count",
            "error_report",
            "started_at",
            "completed_at",
            "download_url",
            "created_at",
        ]

    def get_download_url(self, obj):
        request = self.context.get("request")
        if not request or not obj.csv_file:
            return ""
        return request.build_absolute_uri(f"/api/report-runs/{obj.id}/download/")


class ReportDefinitionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ReportDefinitionSerializer
    search_fields = ["code", "name", "description"]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return visible_report_definitions(self.request.user)

    @action(detail=True, methods=["post"])
    def run(self, request, pk=None):
        definition = self.get_object()
        try:
            report_run = run_report(
                definition.code,
                parameters=request.data.get("parameters", request.data),
                actor=request.user,
            )
        except ReportPermissionError as exc:
            raise PermissionDenied(str(exc)) from exc
        return Response(
            ReportRunSerializer(report_run, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class ReportRunViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ReportRunSerializer
    permission_classes = [IsAuthenticated]
    search_fields = ["code", "name", "status"]

    def get_queryset(self):
        codes = visible_report_codes(self.request.user)
        return (
            ReportRun.objects.filter(code__in=codes)
            .select_related("report_definition", "requested_by")
            .order_by("-created_at")
        )

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        report_run = self.get_object()
        if report_run.status != ReportRun.Status.COMPLETED or not report_run.csv_file:
            raise PermissionDenied("Report CSV is not available.")
        return FileResponse(
            report_run.csv_file.open("rb"),
            as_attachment=True,
            filename=report_run.csv_file.name.rsplit("/", 1)[-1],
            content_type="text/csv",
        )


def register(router):
    router.register("report-definitions", ReportDefinitionViewSet, basename="report-definition")
    router.register("report-runs", ReportRunViewSet, basename="report-run")
