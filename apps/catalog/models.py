from django.db import models

from apps.core.models import BaseModel


class Work(BaseModel):
    primary_title = models.CharField(max_length=512)
    original_title = models.CharField(max_length=512, blank=True)
    form = models.CharField(max_length=128, blank=True)
    date = models.CharField(max_length=64, blank=True)
    language_hint = models.CharField(max_length=16, blank=True)
    summary = models.TextField(blank=True)
    subjects = models.ManyToManyField("vocabularies.VocabularyTerm", blank=True)
    authorities = models.ManyToManyField(
        "authorities.AuthorityRecord", through="WorkAuthorityLink", blank=True
    )

    class Meta:
        indexes = [models.Index(fields=["primary_title"]), models.Index(fields=["date"])]

    def __str__(self) -> str:
        return self.primary_title


class Expression(BaseModel):
    work = models.ForeignKey(Work, on_delete=models.CASCADE, related_name="expressions")
    title = models.CharField(max_length=512, blank=True)
    language = models.CharField(max_length=16, blank=True)
    content_type = models.CharField(max_length=128, blank=True)
    expression_note = models.TextField(blank=True)
    translators = models.ManyToManyField("authorities.AuthorityRecord", blank=True)

    class Meta:
        indexes = [models.Index(fields=["language", "content_type"])]

    def __str__(self) -> str:
        return self.title or f"{self.work} [{self.language}]"


class Instance(BaseModel):
    class ResourceType(models.TextChoices):
        BOOK = "book", "Book"
        SERIAL = "serial", "Serial"
        MAP = "map", "Map"
        SCORE = "score", "Score"
        AV = "av", "Audio/visual"
        DIGITAL = "digital", "Digital"
        MIXED = "mixed", "Mixed material"

    work = models.ForeignKey(Work, null=True, blank=True, on_delete=models.SET_NULL, related_name="instances")
    expression = models.ForeignKey(
        Expression, null=True, blank=True, on_delete=models.SET_NULL, related_name="instances"
    )
    resource_type = models.CharField(max_length=32, choices=ResourceType.choices, default=ResourceType.BOOK)
    title_statement = models.CharField(max_length=1024)
    variant_titles = models.JSONField(default=list, blank=True)
    responsibility_statement = models.CharField(max_length=1024, blank=True)
    edition_statement = models.CharField(max_length=512, blank=True)
    publication_place = models.CharField(max_length=255, blank=True)
    publisher = models.CharField(max_length=512, blank=True)
    publication_date = models.CharField(max_length=128, blank=True)
    extent = models.CharField(max_length=255, blank=True)
    content_type = models.CharField(max_length=128, blank=True)
    media_type = models.CharField(max_length=128, blank=True)
    carrier_type = models.CharField(max_length=128, blank=True)
    identifiers = models.JSONField(default=list, blank=True)
    notes = models.JSONField(default=list, blank=True)
    contributors = models.ManyToManyField("authorities.AuthorityRecord", through="InstanceContributor", blank=True)
    classifications = models.ManyToManyField("vocabularies.ClassificationNumber", blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["resource_type"]),
            models.Index(fields=["title_statement"]),
            models.Index(fields=["publisher"]),
            models.Index(fields=["publication_date"]),
        ]

    def __str__(self) -> str:
        return self.title_statement


class BibliographicRecord(BaseModel):
    class Status(models.TextChoices):
        IMPORTED = "imported", "Imported"
        REVIEW = "review", "Review"
        APPROVED = "approved", "Approved"
        SUPPRESSED = "suppressed", "Suppressed"

    source = models.CharField(max_length=128, blank=True)
    control_number = models.CharField(max_length=128, blank=True)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.IMPORTED)
    encoding_level = models.CharField(max_length=8, blank=True)
    work = models.ForeignKey(Work, null=True, blank=True, on_delete=models.SET_NULL, related_name="bib_records")
    instance = models.ForeignKey(
        Instance, null=True, blank=True, on_delete=models.SET_NULL, related_name="bib_records"
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = [("source", "control_number")]
        indexes = [models.Index(fields=["status"]), models.Index(fields=["control_number"])]

    def __str__(self) -> str:
        return self.control_number or str(self.id)


class WorkAuthorityLink(BaseModel):
    class Role(models.TextChoices):
        CREATOR = "creator", "Creator"
        SUBJECT = "subject", "Subject"
        RELATED_WORK = "related_work", "Related work"

    work = models.ForeignKey(Work, on_delete=models.CASCADE)
    authority = models.ForeignKey("authorities.AuthorityRecord", on_delete=models.CASCADE)
    role = models.CharField(max_length=32, choices=Role.choices)
    relationship_designator = models.CharField(max_length=128, blank=True)

    class Meta:
        unique_together = [("work", "authority", "role", "relationship_designator")]


class InstanceContributor(BaseModel):
    instance = models.ForeignKey(Instance, on_delete=models.CASCADE)
    authority = models.ForeignKey("authorities.AuthorityRecord", on_delete=models.CASCADE)
    role = models.CharField(max_length=128, blank=True)
    marc_tag = models.CharField(max_length=8, blank=True)

    class Meta:
        unique_together = [("instance", "authority", "role", "marc_tag")]

