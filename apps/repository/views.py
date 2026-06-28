from django.core.exceptions import PermissionDenied
from django.http import FileResponse
from django.shortcuts import get_object_or_404, render

from .models import FileAsset
from .services import assert_download_allowed, public_file_assets, published_objects


def repository_list(request):
    query = request.GET.get("q", "").strip()
    objects = published_objects()
    if query:
        lowered = query.lower()
        objects = [
            obj
            for obj in objects
            if lowered in obj.title.lower() or lowered in str(obj.dc_metadata).lower()
        ]
        objects = objects[:100]
    else:
        objects = objects.order_by("title")[:100]
    return render(
        request,
        "repository/list.html",
        {"objects": objects, "query": query},
    )


def repository_detail(request, object_id):
    obj = get_object_or_404(published_objects(), id=object_id)
    return render(
        request,
        "repository/detail.html",
        {"object": obj, "public_files": public_file_assets(obj)},
    )


def file_download(request, asset_id):
    asset = get_object_or_404(
        FileAsset.objects.select_related("digital_object"),
        id=asset_id,
    )
    try:
        assert_download_allowed(request.user, asset)
    except PermissionDenied:
        raise PermissionDenied("File is not publicly available.") from None
    return FileResponse(
        asset.file.open("rb"),
        as_attachment=True,
        filename=asset.file.name.rsplit("/", 1)[-1],
        content_type=asset.mime_type or "application/octet-stream",
    )
