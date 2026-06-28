from django.db import models

from apps.core.models import BaseModel


class SearchDocument(BaseModel):
    instance = models.OneToOneField(
        "catalog.Instance", on_delete=models.CASCADE, related_name="search_document"
    )
    title_main = models.TextField()
    title_variant = models.TextField(blank=True)
    creator = models.TextField(blank=True)
    subject = models.TextField(blank=True)
    identifiers = models.TextField(blank=True)
    publisher = models.TextField(blank=True)
    publication_date = models.CharField(max_length=128, blank=True)
    language = models.CharField(max_length=64, blank=True)
    resource_type = models.CharField(max_length=64, blank=True)
    facets = models.JSONField(default=dict, blank=True)
    availability = models.CharField(max_length=64, default="unknown")
    full_text = models.TextField(blank=True)
    normalized_text = models.TextField(blank=True)
    cjk_tokens = models.TextField(blank=True)
    year_sort = models.IntegerField(null=True, blank=True)
    availability_updated_at = models.DateTimeField(null=True, blank=True)
    indexed_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["resource_type", "availability"]),
            models.Index(fields=["publication_date"]),
            models.Index(fields=["year_sort"]),
        ]

    def __str__(self) -> str:
        return self.title_main[:120]
