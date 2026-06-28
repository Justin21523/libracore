from rest_framework import serializers

from .models import (
    BoundVolume,
    ClaimEvent,
    Issue,
    IssuePredictionPattern,
    SerialCheckInEvent,
    SerialTitle,
    Subscription,
)


class SerialTitleSerializer(serializers.ModelSerializer):
    class Meta:
        model = SerialTitle
        fields = "__all__"


class SubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subscription
        fields = "__all__"


class IssuePredictionPatternSerializer(serializers.ModelSerializer):
    class Meta:
        model = IssuePredictionPattern
        fields = "__all__"


class IssueSerializer(serializers.ModelSerializer):
    class Meta:
        model = Issue
        fields = "__all__"


class SerialCheckInEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = SerialCheckInEvent
        fields = "__all__"


class ClaimEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClaimEvent
        fields = "__all__"


class BoundVolumeSerializer(serializers.ModelSerializer):
    class Meta:
        model = BoundVolume
        fields = "__all__"


class GenerateIssuesSerializer(serializers.Serializer):
    count = serializers.IntegerField(min_value=1)


class ClaimIssueSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True)


class BindIssuesSerializer(serializers.Serializer):
    issue_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False)
    label = serializers.CharField()
