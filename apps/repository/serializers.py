from rest_framework import serializers

from .models import DigitalObject, FileAsset


class FileAssetSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = FileAsset
        fields = "__all__"
        read_only_fields = ["size_bytes", "checksum_sha256"]

    def get_download_url(self, obj):
        request = self.context.get("request")
        url = f"/repository/files/{obj.id}/download/"
        return request.build_absolute_uri(url) if request else url


class DigitalObjectSerializer(serializers.ModelSerializer):
    file_assets = FileAssetSerializer(many=True, read_only=True)
    public_url = serializers.SerializerMethodField()

    class Meta:
        model = DigitalObject
        fields = "__all__"

    def get_public_url(self, obj):
        request = self.context.get("request")
        url = f"/repository/{obj.id}/"
        return request.build_absolute_uri(url) if request else url
