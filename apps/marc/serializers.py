from rest_framework import serializers

from .models import (
    AuthorityLinkSuggestion,
    MarcImportBatch,
    MarcImportRecord,
    MarcMatchCandidate,
    MarcRecord,
)


class MarcRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarcRecord
        fields = "__all__"


class MarcImportBatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarcImportBatch
        fields = "__all__"
        read_only_fields = [
            "submitted_by",
            "status",
            "started_at",
            "completed_at",
            "record_count",
            "valid_count",
            "invalid_count",
            "conflict_count",
        ]


class MarcImportRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarcImportRecord
        fields = "__all__"


class MarcMatchCandidateSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarcMatchCandidate
        fields = "__all__"


class AuthorityLinkSuggestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuthorityLinkSuggestion
        fields = "__all__"


class MarcImportBatchCreateSerializer(serializers.Serializer):
    source = serializers.CharField(required=False, allow_blank=True)
    import_format = serializers.ChoiceField(choices=MarcImportBatch.ImportFormat.choices)
    filename = serializers.CharField(required=False, allow_blank=True)
    payload = serializers.CharField()


class MarcImportUploadSerializer(serializers.Serializer):
    source = serializers.CharField(required=False, allow_blank=True)
    import_format = serializers.ChoiceField(choices=MarcImportBatch.ImportFormat.choices)
    file = serializers.FileField()


class MarcApproveSerializer(serializers.Serializer):
    mapped_overrides = serializers.JSONField(required=False)


class MarcRejectSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True)


class MarcResolveSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["create_new", "link_existing", "overlay_existing"])
    target_id = serializers.CharField(required=False, allow_blank=True)
    mapped_overrides = serializers.JSONField(required=False)


class AuthoritySuggestionAcceptSerializer(serializers.Serializer):
    authority_id = serializers.UUIDField()
