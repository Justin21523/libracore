from rest_framework import serializers

from .models import AccessPoint, AuthorityRecord, AuthorityRelation, ExternalIdentifier
from .services import AuthorityError, validate_external_identifier


class AuthorityRecordSerializer(serializers.ModelSerializer):
    preferred_label = serializers.SerializerMethodField()

    class Meta:
        model = AuthorityRecord
        fields = "__all__"

    def get_preferred_label(self, obj):
        preferred = obj.access_points.filter(kind=AccessPoint.Kind.AUTHORIZED, is_preferred=True).first()
        return preferred.label if preferred else str(obj)


class AccessPointSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccessPoint
        fields = "__all__"
        read_only_fields = ["normalized_label", "sort_key"]


class AuthorityRelationSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuthorityRelation
        fields = "__all__"


class ExternalIdentifierSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExternalIdentifier
        fields = "__all__"

    def validate(self, attrs):
        try:
            validate_external_identifier(attrs.get("scheme", ""), attrs.get("value", ""), attrs.get("uri", ""))
        except AuthorityError as exc:
            raise serializers.ValidationError({"code": exc.code, "detail": str(exc)}) from exc
        return attrs


class AuthorityCreateSerializer(serializers.Serializer):
    authority_type = serializers.ChoiceField(choices=AuthorityRecord.AuthorityType.choices)
    preferred_label = serializers.CharField()
    source = serializers.CharField(required=False, allow_blank=True, default="local")
    control_number = serializers.CharField(required=False, allow_blank=True)
    entity_uri = serializers.URLField(required=False, allow_blank=True)
    status = serializers.ChoiceField(choices=AuthorityRecord.Status.choices, default=AuthorityRecord.Status.PROVISIONAL)


class AccessPointInputSerializer(serializers.Serializer):
    label = serializers.CharField()
    kind = serializers.ChoiceField(choices=AccessPoint.Kind.choices, default=AccessPoint.Kind.VARIANT)
    language = serializers.CharField(required=False, allow_blank=True)
    script = serializers.CharField(required=False, allow_blank=True)
    romanization = serializers.CharField(required=False, allow_blank=True)
    source_field = serializers.CharField(required=False, allow_blank=True)
    is_preferred = serializers.BooleanField(default=False)


class SetPreferredSerializer(serializers.Serializer):
    access_point_id = serializers.UUIDField()


class AuthorityRelationInputSerializer(serializers.Serializer):
    target_id = serializers.UUIDField()
    relation_type = serializers.ChoiceField(choices=AuthorityRelation.RelationType.choices)
    note = serializers.CharField(required=False, allow_blank=True)


class AuthorityMergeSerializer(serializers.Serializer):
    target_id = serializers.UUIDField()
    note = serializers.CharField(required=False, allow_blank=True)


class AuthorityDeprecateSerializer(serializers.Serializer):
    replacement_id = serializers.UUIDField(required=False)
    note = serializers.CharField(required=False, allow_blank=True)

