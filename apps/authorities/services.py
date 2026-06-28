from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from apps.catalog.models import InstanceContributor, WorkAuthorityLink
from apps.core.models import AuditLog
from apps.discovery.cjk import normalize_text
from apps.marc.models import AuthorityLinkSuggestion, MarcRecord

from .models import AccessPoint, AuthorityRecord, AuthorityRelation, ExternalIdentifier


class AuthorityError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ActorContext:
    actor: object | None = None
    ip_address: str | None = None
    user_agent: str = ""


def normalize_heading(label: str) -> str:
    return normalize_text(label)


def sort_key_for_label(label: str) -> str:
    return normalize_heading(label)


@transaction.atomic
def create_authority(
    *,
    authority_type: str,
    preferred_label: str,
    source: str = "local",
    control_number: str = "",
    entity_uri: str = "",
    status: str = AuthorityRecord.Status.PROVISIONAL,
    actor_context: ActorContext | None = None,
) -> AuthorityRecord:
    actor_context = actor_context or ActorContext()
    authority = AuthorityRecord.objects.create(
        authority_type=authority_type,
        source=source,
        control_number=control_number,
        entity_uri=entity_uri,
        status=status,
    )
    _create_access_point(
        authority=authority,
        kind=AccessPoint.Kind.AUTHORIZED,
        label=preferred_label,
        is_preferred=True,
    )
    _audit("authority_created", authority, {}, {"preferred_label": preferred_label}, actor_context)
    return authority


@transaction.atomic
def set_preferred_access_point(*, authority_id, access_point_id, actor_context: ActorContext | None = None) -> AccessPoint:
    actor_context = actor_context or ActorContext()
    authority = AuthorityRecord.objects.select_for_update().get(id=authority_id)
    access_point = authority.access_points.select_for_update().get(id=access_point_id)
    if access_point.kind != AccessPoint.Kind.AUTHORIZED:
        raise AuthorityError("variant_cannot_be_preferred", "Only authorized access points can be preferred.")
    before = {
        "preferred": [
            str(value)
            for value in authority.access_points.filter(is_preferred=True).values_list("id", flat=True)
        ]
    }
    authority.access_points.update(is_preferred=False)
    access_point.is_preferred = True
    access_point.save(update_fields=["is_preferred", "updated_at"])
    _audit("authority_preferred_access_point_set", authority, before, {"preferred": str(access_point.id)}, actor_context)
    return access_point


@transaction.atomic
def add_access_point(
    *,
    authority_id,
    label: str,
    kind: str = AccessPoint.Kind.VARIANT,
    language: str = "",
    script: str = "",
    romanization: str = "",
    source_field: str = "",
    is_preferred: bool = False,
    actor_context: ActorContext | None = None,
) -> AccessPoint:
    actor_context = actor_context or ActorContext()
    authority = AuthorityRecord.objects.select_for_update().get(id=authority_id)
    if kind == AccessPoint.Kind.VARIANT and is_preferred:
        raise AuthorityError("variant_cannot_be_preferred", "Variant access points cannot be preferred.")
    if kind == AccessPoint.Kind.AUTHORIZED and is_preferred:
        authority.access_points.update(is_preferred=False)
    access_point = _create_access_point(
        authority=authority,
        kind=kind,
        label=label,
        language=language,
        script=script,
        romanization=romanization,
        source_field=source_field,
        is_preferred=is_preferred,
    )
    _audit("authority_access_point_added", access_point, {}, {"label": label, "kind": kind}, actor_context)
    return access_point


def add_variant_access_point(**kwargs) -> AccessPoint:
    kwargs["kind"] = AccessPoint.Kind.VARIANT
    kwargs["is_preferred"] = False
    return add_access_point(**kwargs)


@transaction.atomic
def add_authority_relation(
    *,
    source_id,
    target_id,
    relation_type: str,
    note: str = "",
    actor_context: ActorContext | None = None,
) -> AuthorityRelation:
    actor_context = actor_context or ActorContext()
    if source_id == target_id:
        raise AuthorityError("self_relation_not_allowed", "Authority cannot relate to itself.")
    relation, _ = AuthorityRelation.objects.get_or_create(
        source_id=source_id,
        target_id=target_id,
        relation_type=relation_type,
        defaults={"note": note},
    )
    _audit("authority_relation_added", relation, {}, {"relation_type": relation_type}, actor_context)
    return relation


@transaction.atomic
def merge_authorities(*, source_id, target_id, note: str = "", actor_context: ActorContext | None = None) -> AuthorityRecord:
    actor_context = actor_context or ActorContext()
    if source_id == target_id:
        raise AuthorityError("same_authority", "Source and target authority must be different.")
    source = AuthorityRecord.objects.select_for_update().get(id=source_id)
    target = AuthorityRecord.objects.select_for_update().get(id=target_id)
    if target.status == AuthorityRecord.Status.DEPRECATED and not target.deprecated_replacement_id:
        raise AuthorityError("invalid_target", "Cannot merge into deprecated authority without replacement.")
    before = {"source_status": source.status, "target": str(target.id)}

    for link in list(WorkAuthorityLink.objects.filter(authority=source)):
        WorkAuthorityLink.objects.get_or_create(
            work=link.work,
            authority=target,
            role=link.role,
            relationship_designator=link.relationship_designator,
        )
        link.delete()
    for link in list(InstanceContributor.objects.filter(authority=source)):
        InstanceContributor.objects.get_or_create(
            instance=link.instance,
            authority=target,
            role=link.role,
            marc_tag=link.marc_tag,
        )
        link.delete()
    MarcRecord.objects.filter(authority_record=source).update(authority_record=target)
    AuthorityLinkSuggestion.objects.filter(matched_authority=source).update(matched_authority=target)

    existing_labels = set(target.access_points.values_list("normalized_label", flat=True))
    for access_point in source.access_points.all():
        normalized = normalize_heading(access_point.label)
        if normalized not in existing_labels:
            _create_access_point(
                authority=target,
                kind=AccessPoint.Kind.VARIANT,
                label=access_point.label,
                language=access_point.language,
                script=access_point.script,
                romanization=access_point.romanization,
                source_field=access_point.source_field,
                is_preferred=False,
            )
            existing_labels.add(normalized)

    add_authority_relation(
        source_id=source.id,
        target_id=target.id,
        relation_type=AuthorityRelation.RelationType.EQUIVALENT,
        note=note,
        actor_context=actor_context,
    )
    source.status = AuthorityRecord.Status.DEPRECATED
    source.deprecated_replacement = target
    source.deprecated_note = note
    source.save(update_fields=["status", "deprecated_replacement", "deprecated_note", "updated_at"])
    _audit("authority_merged", source, before, {"source_status": source.status, "target": str(target.id)}, actor_context)
    return target


@transaction.atomic
def deprecate_authority(
    *,
    authority_id,
    replacement_id=None,
    note: str = "",
    actor_context: ActorContext | None = None,
) -> AuthorityRecord:
    actor_context = actor_context or ActorContext()
    authority = AuthorityRecord.objects.select_for_update().get(id=authority_id)
    if replacement_id and str(authority.id) == str(replacement_id):
        raise AuthorityError("same_authority", "Replacement cannot be the same authority.")
    before = {"status": authority.status, "replacement": str(authority.deprecated_replacement_id or "")}
    authority.status = AuthorityRecord.Status.DEPRECATED
    authority.deprecated_replacement_id = replacement_id
    authority.deprecated_note = note
    authority.save(update_fields=["status", "deprecated_replacement", "deprecated_note", "updated_at"])
    _audit("authority_deprecated", authority, before, {"status": authority.status}, actor_context)
    return authority


def validate_external_identifier(scheme: str, value: str, uri: str = "") -> None:
    candidate = uri or value
    parsed = urlparse(candidate)
    if scheme in ["lcnaf", "lcsh"] and not candidate.startswith("https://id.loc.gov/authorities/"):
        raise AuthorityError("invalid_external_uri", "Library of Congress authority URI must use id.loc.gov/authorities.")
    if scheme == "viaf" and not candidate.startswith("https://viaf.org/viaf/"):
        raise AuthorityError("invalid_external_uri", "VIAF URI must use https://viaf.org/viaf/.")
    if scheme == "orcid" and not candidate.startswith("https://orcid.org/"):
        raise AuthorityError("invalid_external_uri", "ORCID URI must use https://orcid.org/.")
    if scheme == "fast" and parsed.scheme and "fast.oclc.org" not in parsed.netloc:
        raise AuthorityError("invalid_external_uri", "FAST URI must use fast.oclc.org when URI is provided.")


@transaction.atomic
def add_external_identifier(
    *,
    authority_id,
    scheme: str,
    value: str,
    uri: str = "",
    actor_context: ActorContext | None = None,
) -> ExternalIdentifier:
    actor_context = actor_context or ActorContext()
    validate_external_identifier(scheme, value, uri)
    identifier = ExternalIdentifier.objects.create(
        authority_id=authority_id,
        scheme=scheme,
        value=value,
        uri=uri,
    )
    _audit("authority_external_identifier_added", identifier, {}, {"scheme": scheme, "value": value}, actor_context)
    return identifier


def _create_access_point(
    *,
    authority: AuthorityRecord,
    kind: str,
    label: str,
    language: str = "",
    script: str = "",
    romanization: str = "",
    source_field: str = "",
    is_preferred: bool = False,
) -> AccessPoint:
    return AccessPoint.objects.create(
        authority=authority,
        kind=kind,
        label=label,
        normalized_label=normalize_heading(label),
        sort_key=sort_key_for_label(label),
        language=language,
        script=script,
        romanization=romanization,
        source_field=source_field,
        is_preferred=is_preferred,
    )


def _audit(action: str, entity, before: dict, after: dict, actor_context: ActorContext) -> None:
    AuditLog.objects.create(
        actor=actor_context.actor if getattr(actor_context.actor, "is_authenticated", False) else None,
        action=action,
        entity_type=ContentType.objects.get_for_model(entity.__class__),
        entity_id=str(entity.id),
        before=before,
        after=after,
        ip_address=actor_context.ip_address,
        user_agent=actor_context.user_agent,
    )
