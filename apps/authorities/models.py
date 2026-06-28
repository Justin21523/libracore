from django.db import models

from apps.core.models import BaseModel


class AuthorityRecord(BaseModel):
    class AuthorityType(models.TextChoices):
        PERSON = "person", "Person"
        FAMILY = "family", "Family"
        CORPORATE_BODY = "corporate_body", "Corporate body"
        CONFERENCE = "conference", "Conference"
        WORK_TITLE = "work_title", "Work or uniform title"
        SUBJECT = "subject", "Subject"
        GENRE = "genre", "Genre"
        PLACE = "place", "Place"

    class Status(models.TextChoices):
        PROVISIONAL = "provisional", "Provisional"
        AUTHORIZED = "authorized", "Authorized"
        DEPRECATED = "deprecated", "Deprecated"

    authority_type = models.CharField(max_length=32, choices=AuthorityType.choices)
    source = models.CharField(max_length=64, blank=True)
    control_number = models.CharField(max_length=128, blank=True)
    entity_uri = models.URLField(blank=True)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PROVISIONAL)
    deprecated_replacement = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="deprecated_sources",
    )
    deprecated_note = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "control_number"],
                condition=~models.Q(control_number=""),
                name="unique_authority_source_control_number_when_present",
            )
        ]
        indexes = [
            models.Index(fields=["authority_type", "status"]),
            models.Index(fields=["entity_uri"]),
        ]

    def __str__(self) -> str:
        preferred = self.access_points.filter(kind=AccessPoint.Kind.AUTHORIZED).first()
        return preferred.label if preferred else f"{self.authority_type}:{self.id}"


class AccessPoint(BaseModel):
    class Kind(models.TextChoices):
        AUTHORIZED = "authorized", "Authorized"
        VARIANT = "variant", "Variant"

    authority = models.ForeignKey(
        AuthorityRecord, on_delete=models.CASCADE, related_name="access_points"
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    label = models.CharField(max_length=512)
    normalized_label = models.CharField(max_length=512, blank=True)
    sort_key = models.CharField(max_length=512, blank=True)
    language = models.CharField(max_length=16, blank=True)
    script = models.CharField(max_length=32, blank=True)
    romanization = models.CharField(max_length=128, blank=True)
    source_field = models.CharField(max_length=32, blank=True)
    is_preferred = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["kind", "label"]),
            models.Index(fields=["language", "script"]),
        ]

    def __str__(self) -> str:
        return self.label


class AuthorityRelation(BaseModel):
    class RelationType(models.TextChoices):
        EQUIVALENT = "equivalent", "Equivalent"
        BROADER = "broader", "Broader"
        NARROWER = "narrower", "Narrower"
        RELATED = "related", "Related"
        EARLIER_NAME = "earlier_name", "Earlier name"
        LATER_NAME = "later_name", "Later name"
        SEE = "see", "See"
        SEE_ALSO = "see_also", "See also"

    source = models.ForeignKey(
        AuthorityRecord, on_delete=models.CASCADE, related_name="outgoing_relations"
    )
    target = models.ForeignKey(
        AuthorityRecord, on_delete=models.CASCADE, related_name="incoming_relations"
    )
    relation_type = models.CharField(max_length=32, choices=RelationType.choices)
    note = models.TextField(blank=True)

    class Meta:
        unique_together = [("source", "target", "relation_type")]


class ExternalIdentifier(BaseModel):
    authority = models.ForeignKey(
        AuthorityRecord, on_delete=models.CASCADE, related_name="external_identifiers"
    )
    scheme = models.CharField(max_length=64)
    value = models.CharField(max_length=256)
    uri = models.URLField(blank=True)

    class Meta:
        unique_together = [("scheme", "value")]


class AuthorizedAccessPoint(AccessPoint):
    class Meta:
        proxy = True
        verbose_name = "Authorized access point"
        verbose_name_plural = "Authorized access points"


class VariantAccessPoint(AccessPoint):
    class Meta:
        proxy = True
        verbose_name = "Variant access point"
        verbose_name_plural = "Variant access points"
