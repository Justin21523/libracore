from __future__ import annotations

from dataclasses import dataclass

from django.core.paginator import Paginator
from django.db import connection
from django.db.models import Q

from .cjk import normalize_query
from .models import SearchDocument


@dataclass
class SearchResultPage:
    page_obj: object
    total: int
    facets: dict
    query: str
    filters: dict


def search_documents(
    query: str = "", filters: dict | None = None, page: int = 1, per_page: int = 10
) -> SearchResultPage:
    filters = filters or {}
    queryset = SearchDocument.objects.select_related("instance").all()
    queryset = _apply_query(queryset, query)
    results = _apply_filters(queryset, filters)
    if hasattr(results, "order_by"):
        results = results.order_by("title_main")
    else:
        results = sorted(results, key=lambda document: document.title_main)
    paginator = Paginator(results, per_page)
    page_obj = paginator.get_page(page)
    return SearchResultPage(
        page_obj=page_obj,
        total=paginator.count,
        facets=facet_counts(query, filters),
        query=query,
        filters=filters,
    )


def facet_counts(query: str = "", filters: dict | None = None) -> dict:
    filters = filters or {}
    queryset = SearchDocument.objects.all()
    queryset = _apply_query(queryset, query)
    results = _apply_filters(queryset, filters)
    counters = {
        "resource_type": {},
        "availability": {},
        "branch": {},
        "location": {},
        "language": {},
        "year": {},
        "online_available": {},
        "platform": {},
        "resource_mode": {},
        "repository_available": {},
        "file_mime_type": {},
        "file_access_level": {},
    }
    for document in results:
        _add_count(counters["resource_type"], document.resource_type)
        _add_count(counters["availability"], document.availability)
        _add_count(counters["language"], document.language)
        _add_count(counters["year"], str(document.year_sort) if document.year_sort else "")
        for branch in document.facets.get("branch_name", []):
            _add_count(counters["branch"], branch)
        for location in document.facets.get("location_name", []):
            _add_count(counters["location"], location)
        for online_available in document.facets.get("online_available", []):
            _add_count(counters["online_available"], online_available)
        for platform in document.facets.get("platform_name", []):
            _add_count(counters["platform"], platform)
        for resource_mode in document.facets.get("resource_mode", []):
            _add_count(counters["resource_mode"], resource_mode)
        for repository_available in document.facets.get("repository_available", []):
            _add_count(counters["repository_available"], repository_available)
        for mime_type in document.facets.get("file_mime_type", []):
            _add_count(counters["file_mime_type"], mime_type)
        for access_level in document.facets.get("file_access_level", []):
            _add_count(counters["file_access_level"], access_level)
    return counters


def _apply_query(queryset, query: str):
    if not query:
        return queryset
    normalized, cjk_tokens = normalize_query(query)
    if connection.vendor == "postgresql":
        from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector

        vector = (
            SearchVector("title_main", weight="A")
            + SearchVector("creator", weight="A")
            + SearchVector("identifiers", weight="A")
            + SearchVector("subject", weight="B")
            + SearchVector("publisher", weight="C")
            + SearchVector("full_text", weight="D")
            + SearchVector("normalized_text", weight="B")
            + SearchVector("cjk_tokens", weight="B")
        )
        search_query = SearchQuery(query, search_type="websearch")
        return (
            queryset.annotate(rank=SearchRank(vector, search_query))
            .filter(
                Q(rank__gt=0)
                | Q(normalized_text__icontains=normalized)
                | Q(cjk_tokens__icontains=cjk_tokens)
            )
            .order_by("-rank", "title_main")
        )
    terms = [query, normalized, *cjk_tokens.split()]
    condition = Q()
    for term in [term for term in terms if term]:
        condition |= Q(normalized_text__icontains=term) | Q(cjk_tokens__icontains=term)
    return queryset.filter(condition)


def _apply_filters(queryset, filters: dict):
    if filters.get("resource_type"):
        queryset = queryset.filter(resource_type=filters["resource_type"])
    if filters.get("availability"):
        queryset = queryset.filter(availability=filters["availability"])
    if filters.get("language"):
        queryset = queryset.filter(language=filters["language"])
    if filters.get("year"):
        queryset = queryset.filter(year_sort=filters["year"])
    online_available = filters.get("online_available")
    platform = filters.get("platform")
    resource_mode = filters.get("resource_mode")
    repository_available = filters.get("repository_available")
    file_mime_type = filters.get("file_mime_type")
    branch = filters.get("branch")
    location = filters.get("location")
    if online_available:
        queryset = [
            document
            for document in queryset
            if online_available in document.facets.get("online_available", [])
        ]
    if platform:
        queryset = [
            document
            for document in queryset
            if platform in document.facets.get("platform", [])
            or platform in document.facets.get("platform_name", [])
        ]
    if resource_mode:
        queryset = [
            document
            for document in queryset
            if resource_mode in document.facets.get("resource_mode", [])
        ]
    if repository_available:
        queryset = [
            document
            for document in queryset
            if repository_available in document.facets.get("repository_available", [])
        ]
    if file_mime_type:
        queryset = [
            document
            for document in queryset
            if file_mime_type in document.facets.get("file_mime_type", [])
        ]
    if branch:
        queryset = [
            document
            for document in queryset
            if branch in document.facets.get("branch", [])
            or branch in document.facets.get("branch_name", [])
        ]
    if location:
        queryset = [
            document
            for document in queryset
            if location in document.facets.get("location", [])
            or location in document.facets.get("location_name", [])
        ]
    return queryset


def _add_count(counter: dict, value: str) -> None:
    if value:
        counter[value] = counter.get(value, 0) + 1
