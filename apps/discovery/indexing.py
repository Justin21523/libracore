from __future__ import annotations

import re
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.authorities.models import AccessPoint
from apps.catalog.models import (
    BibliographicRecord,
    Instance,
    InstanceContributor,
    WorkAuthorityLink,
)
from apps.erm.services import erm_index_values
from apps.holdings.models import Item
from apps.repository.services import repository_index_values
from apps.serials.models import Issue, SerialTitle

from .cjk import normalize_text, tokenize_cjk
from .models import SearchDocument


@dataclass(frozen=True)
class IndexStats:
    indexed: int = 0
    removed: int = 0


def rebuild_all_indexes() -> IndexStats:
    indexed = 0
    approved_instance_ids = set(
        BibliographicRecord.objects.filter(status=BibliographicRecord.Status.APPROVED)
        .exclude(instance__isnull=True)
        .values_list("instance_id", flat=True)
    )
    removed, _ = SearchDocument.objects.exclude(instance_id__in=approved_instance_ids).delete()
    for instance_id in approved_instance_ids:
        if rebuild_instance_index(instance_id):
            indexed += 1
    return IndexStats(indexed=indexed, removed=removed)


def rebuild_instance_index(instance_id) -> SearchDocument | None:
    instance = (
        Instance.objects.select_related("work", "expression")
        .prefetch_related("holdings__items", "holdings__branch", "holdings__location")
        .filter(id=instance_id)
        .first()
    )
    if not instance:
        return None
    if not BibliographicRecord.objects.filter(
        instance=instance, status=BibliographicRecord.Status.APPROVED
    ).exists():
        SearchDocument.objects.filter(instance=instance).delete()
        return None
    return build_search_document(instance)


@transaction.atomic
def build_search_document(instance: Instance) -> SearchDocument:
    bibs = list(
        BibliographicRecord.objects.filter(
            instance=instance, status=BibliographicRecord.Status.APPROVED
        )
    )
    work = instance.work
    creators = _authority_labels_for_instance(
        instance, ["creator", "contributor"], preferred_only=True
    )
    authority_search_labels = _authority_labels_for_instance(
        instance, ["creator", "contributor", "subject"], preferred_only=False
    )
    subjects = _subject_labels(instance, bibs)
    identifiers = _identifier_text(instance, bibs)
    holdings = list(
        instance.holdings.select_related("branch", "location", "call_number").prefetch_related(
            "items"
        )
    )
    availability = _availability_for_holdings(holdings)
    branch_names = sorted({holding.branch.name for holding in holdings})
    branch_codes = sorted({holding.branch.code for holding in holdings})
    location_names = sorted(
        {holding.location.name for holding in holdings if holding.location.is_public}
    )
    location_codes = sorted(
        {holding.location.code for holding in holdings if holding.location.is_public}
    )
    year_sort = _extract_year(instance.publication_date)
    language = (work.language_hint if work else "") or ""
    title_parts = [instance.title_statement, work.primary_title if work else ""]
    variant_titles = " ".join(instance.variant_titles or [])
    notes = " ".join(note.get("value", "") for note in instance.notes if isinstance(note, dict))
    serial_text, serial_facets = _serial_index_values(instance)
    erm_text, erm_facets = erm_index_values(instance)
    repository_text, repository_facets = repository_index_values(instance)
    all_text = " ".join(
        [
            *title_parts,
            variant_titles,
            instance.responsibility_statement,
            " ".join(creators),
            " ".join(authority_search_labels),
            " ".join(subjects),
            identifiers,
            instance.publisher,
            instance.publication_date,
            notes,
            serial_text,
            erm_text,
            repository_text,
        ]
    )
    normalized_text = " ".join(
        sorted({*title_parts, normalize_text(all_text), *cjk_variants_for_index(all_text)})
    )
    cjk_tokens = tokenize_cjk(all_text)
    facets = {
        "branch": branch_codes,
        "branch_name": branch_names,
        "location": location_codes,
        "location_name": location_names,
        "resource_type": [instance.resource_type] if instance.resource_type else [],
        "language": [language] if language else [],
        "publisher": [instance.publisher] if instance.publisher else [],
        "year": [str(year_sort)] if year_sort else [],
        "availability": [availability],
        "subjects": subjects,
        **serial_facets,
        **erm_facets,
        **repository_facets,
    }
    return SearchDocument.objects.update_or_create(
        instance=instance,
        defaults={
            "title_main": instance.title_statement,
            "title_variant": variant_titles,
            "creator": " ; ".join(creators),
            "subject": " ; ".join(subjects),
            "identifiers": identifiers,
            "publisher": instance.publisher,
            "publication_date": instance.publication_date,
            "language": language,
            "resource_type": instance.resource_type,
            "facets": facets,
            "availability": availability,
            "full_text": " ".join(
                value for value in [notes, serial_text, erm_text, repository_text] if value
            ),
            "normalized_text": normalized_text,
            "cjk_tokens": cjk_tokens,
            "year_sort": year_sort,
            "availability_updated_at": timezone.now(),
        },
    )[0]


def cjk_variants_for_index(value: str) -> set[str]:
    from .cjk import cjk_variants

    return cjk_variants(value)


def _authority_labels_for_instance(
    instance: Instance, roles: list[str], preferred_only: bool = False
) -> list[str]:
    labels: list[str] = []
    contributor_authority_ids = InstanceContributor.objects.filter(instance=instance).values_list(
        "authority_id", flat=True
    )
    work_authority_ids = []
    if instance.work_id:
        work_authority_ids = WorkAuthorityLink.objects.filter(work=instance.work).values_list(
            "authority_id", flat=True
        )
    authority_ids = list(contributor_authority_ids) + list(work_authority_ids)
    queryset = AccessPoint.objects.filter(authority_id__in=authority_ids)
    if preferred_only:
        queryset = queryset.filter(is_preferred=True)
    for access_point in queryset:
        labels.append(access_point.label)
    return sorted(set(labels))


def _subject_labels(instance: Instance, bibs: list[BibliographicRecord]) -> list[str]:
    labels: set[str] = set()
    if instance.work_id:
        labels.update(instance.work.subjects.values_list("label", flat=True))
        subject_authority_ids = WorkAuthorityLink.objects.filter(
            work=instance.work,
            role=WorkAuthorityLink.Role.SUBJECT,
        ).values_list("authority_id", flat=True)
        labels.update(
            AccessPoint.objects.filter(
                authority_id__in=subject_authority_ids, is_preferred=True
            ).values_list("label", flat=True)
        )
    for bib in bibs:
        for subject in bib.metadata.get("subjects", []):
            if isinstance(subject, dict) and subject.get("label"):
                labels.add(subject["label"])
    return sorted(labels)


def _identifier_text(instance: Instance, bibs: list[BibliographicRecord]) -> str:
    values = []
    for identifier in instance.identifiers:
        if isinstance(identifier, dict):
            values.append(identifier.get("value", ""))
    values.extend(bib.control_number for bib in bibs if bib.control_number)
    return " ".join(value for value in values if value)


def _serial_index_values(instance: Instance) -> tuple[str, dict]:
    serial = (
        SerialTitle.objects.filter(instance=instance)
        .select_related("holding")
        .prefetch_related("issues")
        .first()
    )
    if not serial:
        return "", {"serial_status": [], "serial_frequency": []}
    issues = list(serial.issues.all())
    received = [
        issue for issue in issues if issue.status in [Issue.Status.RECEIVED, Issue.Status.BOUND]
    ]
    latest = (
        sorted(
            received, key=lambda issue: (issue.received_at or issue.expected_at, issue.enumeration)
        )[-1:]
        or []
    )
    text_parts = [
        serial.title,
        serial.issn,
        serial.frequency,
        serial.holding.textual_holdings if serial.holding_id else "",
        " ".join(f"{issue.enumeration} {issue.chronology} {issue.status}" for issue in issues),
    ]
    facets = {
        "serial_status": sorted({issue.status for issue in issues}),
        "serial_frequency": [serial.frequency] if serial.frequency else [],
    }
    if latest:
        facets["latest_issue"] = [f"{latest[0].enumeration} {latest[0].chronology}".strip()]
    return " ".join(part for part in text_parts if part), facets


def _availability_for_holdings(holdings) -> str:
    items = [item for holding in holdings for item in holding.items.all()]
    if not holdings or not items:
        return "no_holdings"
    statuses = {item.status for item in items}
    if Item.Status.AVAILABLE in statuses:
        return "available"
    if Item.Status.ON_HOLD in statuses:
        return "on_hold"
    if Item.Status.ON_LOAN in statuses:
        return "on_loan"
    return "unavailable"


def _extract_year(value: str) -> int | None:
    match = re.search(r"(1[5-9]\d{2}|20\d{2}|21\d{2})", value or "")
    return int(match.group(1)) if match else None
