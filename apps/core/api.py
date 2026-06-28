from django.http import HttpResponse
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from .audit import audit_logs_csv, filtered_audit_logs, json_diff, model_snapshot, write_audit_log
from .data_quality import run_data_quality_checks
from .models import AuditLog, DataQualityIssue, DataQualityRun
from .permissions import AdminRolePermission
from .roles import user_is_admin


class BaseModelViewSet(viewsets.ModelViewSet):
    filterset_fields = "__all__"
    ordering = ["-created_at"]

    def destroy(self, request, *args, **kwargs):
        if not user_is_admin(request.user):
            raise PermissionDenied("Admin permission is required for delete operations.")
        return super().destroy(request, *args, **kwargs)

    def perform_create(self, serializer):
        instance = serializer.save()
        write_audit_log(
            action=f"{instance._meta.model_name}_created",
            entity=instance,
            after=model_snapshot(instance),
            actor=self.request.user,
            ip_address=self.request.META.get("REMOTE_ADDR"),
            user_agent=self.request.META.get("HTTP_USER_AGENT", ""),
        )

    def perform_update(self, serializer):
        before = model_snapshot(self.get_object())
        instance = serializer.save()
        write_audit_log(
            action=f"{instance._meta.model_name}_updated",
            entity=instance,
            before=before,
            after=model_snapshot(instance),
            actor=self.request.user,
            ip_address=self.request.META.get("REMOTE_ADDR"),
            user_agent=self.request.META.get("HTTP_USER_AGENT", ""),
        )

    def perform_destroy(self, instance):
        before = model_snapshot(instance)
        if hasattr(instance, "deleted_at"):
            instance.deleted_at = timezone.now()
            instance.save(update_fields=["deleted_at", "updated_at"])
            action = f"{instance._meta.model_name}_soft_deleted"
        else:
            instance.delete()
            action = f"{instance._meta.model_name}_deleted"
        write_audit_log(
            action=action,
            entity=instance,
            before=before,
            actor=self.request.user,
            ip_address=self.request.META.get("REMOTE_ADDR"),
            user_agent=self.request.META.get("HTTP_USER_AGENT", ""),
        )


def serializer_for(model):
    class AutoSerializer(serializers.ModelSerializer):
        class Meta:
            fields = "__all__"

    AutoSerializer.Meta.model = model
    AutoSerializer.__name__ = f"{model.__name__}Serializer"
    return AutoSerializer


class AuditLogSerializer(serializers.ModelSerializer):
    actor_username = serializers.CharField(source="actor.username", read_only=True, default="")
    entity_type_label = serializers.CharField(source="entity_type.model", read_only=True)
    diff = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "created_at",
            "actor",
            "actor_username",
            "action",
            "entity_type",
            "entity_type_label",
            "entity_id",
            "before",
            "after",
            "diff",
            "ip_address",
            "user_agent",
        ]

    def get_diff(self, obj):
        return json_diff(obj.before, obj.after)


class DataQualityRunSerializer(serializers.ModelSerializer):
    started_by_username = serializers.CharField(source="started_by.username", read_only=True)

    class Meta:
        model = DataQualityRun
        fields = "__all__"


class DataQualityIssueSerializer(serializers.ModelSerializer):
    entity_type_label = serializers.CharField(source="entity_type.model", read_only=True)

    class Meta:
        model = DataQualityIssue
        fields = "__all__"


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditLogSerializer
    permission_classes = [AdminRolePermission]
    search_fields = ["action", "entity_id", "actor__username"]

    def get_queryset(self):
        return filtered_audit_logs(self.request.query_params)

    @action(detail=False, methods=["get"])
    def export(self, request):
        response = HttpResponse(audit_logs_csv(self.get_queryset()), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="audit-logs.csv"'
        return response


class DataQualityRunViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DataQualityRun.objects.select_related("started_by").prefetch_related("issues")
    serializer_class = DataQualityRunSerializer
    permission_classes = [AdminRolePermission]

    @action(detail=False, methods=["post"])
    def run(self, request):
        quality_run = run_data_quality_checks(actor=request.user)
        return Response(self.get_serializer(quality_run).data, status=status.HTTP_201_CREATED)


class DataQualityIssueViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DataQualityIssue.objects.select_related("run", "entity_type").all()
    serializer_class = DataQualityIssueSerializer
    permission_classes = [AdminRolePermission]
    search_fields = ["code", "message", "entity_label"]


def register(router):
    router.register("audit-logs", AuditLogViewSet, basename="audit-log")
    router.register("data-quality-runs", DataQualityRunViewSet, basename="data-quality-run")
    router.register("data-quality-issues", DataQualityIssueViewSet, basename="data-quality-issue")
