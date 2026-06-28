from rest_framework import serializers

from .models import ExportJob


class ExportJobSerializer(serializers.ModelSerializer):
    result_file_url = serializers.SerializerMethodField()
    requested_by_username = serializers.CharField(source="requested_by.username", read_only=True)

    class Meta:
        model = ExportJob
        fields = [
            "id",
            "export_type",
            "status",
            "requested_by",
            "requested_by_username",
            "parameters",
            "result_file",
            "result_file_url",
            "record_count",
            "error_report",
            "started_at",
            "completed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "requested_by",
            "requested_by_username",
            "result_file",
            "result_file_url",
            "record_count",
            "error_report",
            "started_at",
            "completed_at",
            "created_at",
            "updated_at",
        ]

    def get_result_file_url(self, obj):
        request = self.context.get("request")
        if not obj.result_file:
            return ""
        url = obj.result_file.url
        return request.build_absolute_uri(url) if request else url


class ExportJobCreateSerializer(serializers.Serializer):
    export_type = serializers.ChoiceField(choices=ExportJob.ExportType.choices)
    parameters = serializers.JSONField(required=False, default=dict)
