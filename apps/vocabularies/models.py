from django.db import models

from apps.core.models import BaseModel


class ControlledVocabulary(BaseModel):
    code = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    source_uri = models.URLField(blank=True)
    language = models.CharField(max_length=16, blank=True)
    is_local = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    def __str__(self) -> str:
        return self.name


class VocabularyTerm(BaseModel):
    vocabulary = models.ForeignKey(
        ControlledVocabulary, on_delete=models.CASCADE, related_name="terms"
    )
    code = models.CharField(max_length=128, blank=True)
    label = models.CharField(max_length=512)
    language = models.CharField(max_length=16, blank=True)
    script = models.CharField(max_length=32, blank=True)
    external_uri = models.URLField(blank=True)
    scope_note = models.TextField(blank=True)
    broader = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="narrower_terms"
    )
    related_terms = models.ManyToManyField("self", blank=True, symmetrical=True)

    class Meta:
        unique_together = [("vocabulary", "code"), ("vocabulary", "label", "language")]
        indexes = [models.Index(fields=["label"]), models.Index(fields=["external_uri"])]

    def __str__(self) -> str:
        return self.label


class ClassificationScheme(BaseModel):
    code = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    edition = models.CharField(max_length=64, blank=True)
    source_uri = models.URLField(blank=True)
    notes = models.TextField(blank=True)

    def __str__(self) -> str:
        return f"{self.name} {self.edition}".strip()


class ClassificationNumber(BaseModel):
    scheme = models.ForeignKey(
        ClassificationScheme, on_delete=models.CASCADE, related_name="numbers"
    )
    number = models.CharField(max_length=128)
    caption = models.CharField(max_length=512, blank=True)
    normalized = models.CharField(max_length=128, blank=True)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children"
    )

    class Meta:
        unique_together = [("scheme", "number")]
        indexes = [models.Index(fields=["number"]), models.Index(fields=["normalized"])]

    def __str__(self) -> str:
        return self.number


class CallNumber(BaseModel):
    classification = models.ForeignKey(
        ClassificationNumber, null=True, blank=True, on_delete=models.SET_NULL
    )
    raw = models.CharField(max_length=255)
    prefix = models.CharField(max_length=64, blank=True)
    cutter = models.CharField(max_length=64, blank=True)
    year = models.CharField(max_length=16, blank=True)
    copy = models.CharField(max_length=32, blank=True)
    normalized_sort_key = models.CharField(max_length=255, db_index=True)

    def __str__(self) -> str:
        return self.raw

