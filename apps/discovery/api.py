from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework import status

from apps.core.api import BaseModelViewSet, serializer_for
from apps.discovery.indexing import rebuild_all_indexes
from apps.discovery.search import facet_counts, search_documents

from .models import SearchDocument


def _require_staff(request):
    if not request.user.is_authenticated or not request.user.is_staff:
        raise PermissionDenied("Staff permission is required.")


class SearchDocumentViewSet(BaseModelViewSet):
    queryset = SearchDocument.objects.select_related("instance").all()
    serializer_class = serializer_for(SearchDocument)
    search_fields = [
        "title_main",
        "title_variant",
        "creator",
        "subject",
        "identifiers",
        "publisher",
        "full_text",
    ]
    ordering_fields = ["title_main", "publication_date", "indexed_at"]

    @action(detail=False, methods=["get"])
    def facets(self, request):
        filters = _filters_from_request(request)
        return Response(facet_counts(request.query_params.get("q", ""), filters))

    @action(detail=False, methods=["get"])
    def search(self, request):
        result_page = search_documents(
            query=request.query_params.get("q", ""),
            filters=_filters_from_request(request),
            page=int(request.query_params.get("page", "1") or 1),
        )
        return Response(
            {
                "count": result_page.total,
                "page": result_page.page_obj.number,
                "num_pages": result_page.page_obj.paginator.num_pages,
                "facets": result_page.facets,
                "results": [self.get_serializer(document).data for document in result_page.page_obj.object_list],
            }
        )

    @action(detail=False, methods=["post"])
    def rebuild(self, request):
        _require_staff(request)
        stats = rebuild_all_indexes()
        return Response({"indexed": stats.indexed, "removed": stats.removed}, status=status.HTTP_200_OK)


def register(router):
    router.register("search-documents", SearchDocumentViewSet, basename="search-document")


def _filters_from_request(request) -> dict:
    keys = ["resource_type", "availability", "branch", "location", "language", "year"]
    return {key: request.query_params.get(key) for key in keys if request.query_params.get(key)}
