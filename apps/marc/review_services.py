from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from apps.authorities.models import AccessPoint, AuthorityRecord, ExternalIdentifier
from apps.catalog.models import (
    BibliographicRecord,
    Instance,
    InstanceContributor,
    Work,
    WorkAuthorityLink,
)
from apps.core.models import AuditLog
from apps.holdings.models import Branch, Holding, Item, Location
from apps.marc.importers import parse_records
from apps.marc.mapping import map_record
from apps.marc.models import (
    AuthorityLinkSuggestion,
    MarcImportBatch,
    MarcImportRecord,
    MarcMatchCandidate,
    MarcRecord,
)
from apps.marc.parser import MarcParseError, validate_parsed_record
from apps.vocabularies.models import CallNumber


class CatalogingError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ActorContext:
    actor: object | None = None
    ip_address: str | None = None
    user_agent: str = ""


def create_import_batch(
    *,
    payload: bytes | str,
    import_format: str,
    source: str = "",
    filename: str = "",
    actor_context: ActorContext | None = None,
) -> MarcImportBatch:
    actor_context = actor_context or ActorContext()
    with transaction.atomic():
        batch = MarcImportBatch.objects.create(
            source=source,
            import_format=import_format,
            filename=filename,
            submitted_by=actor_context.actor
            if getattr(actor_context.actor, "is_authenticated", False)
            else None,
        )
        raw_records = _split_raw_records(payload, import_format)
        for sequence, raw_record in enumerate(raw_records, start=1):
            MarcImportRecord.objects.create(batch=batch, sequence=sequence, raw_payload=raw_record)
        batch.record_count = len(raw_records)
        batch.save(update_fields=["record_count", "updated_at"])
        _audit(
            "marc_import_batch_created",
            batch,
            {},
            {"record_count": batch.record_count},
            actor_context,
        )
        return batch


def parse_import_batch(*, batch_id, actor_context: ActorContext | None = None) -> MarcImportBatch:
    actor_context = actor_context or ActorContext()
    with transaction.atomic():
        batch = MarcImportBatch.objects.select_for_update().get(id=batch_id)
        batch.started_at = batch.started_at or timezone.now()
        batch.status = MarcImportBatch.Status.PENDING
        batch.save(update_fields=["started_at", "status", "updated_at"])
        valid_count = invalid_count = conflict_count = 0
        for record in batch.records.select_for_update().order_by("sequence"):
            _parse_import_record(record, batch)
            generate_authority_suggestions(import_record=record)
            if record.status == MarcImportRecord.Status.INVALID:
                invalid_count += 1
            elif record.status == MarcImportRecord.Status.CONFLICT:
                conflict_count += 1
            else:
                valid_count += 1
        batch.valid_count = valid_count
        batch.invalid_count = invalid_count
        batch.conflict_count = conflict_count
        batch.status = MarcImportBatch.Status.PARSED
        batch.completed_at = timezone.now()
        batch.save(
            update_fields=[
                "valid_count",
                "invalid_count",
                "conflict_count",
                "status",
                "completed_at",
                "updated_at",
            ]
        )
        _audit(
            "marc_import_batch_parsed",
            batch,
            {},
            {
                "valid_count": valid_count,
                "invalid_count": invalid_count,
                "conflict_count": conflict_count,
            },
            actor_context,
        )
        return batch


def approve_import_record(
    *,
    import_record_id,
    mapped_overrides: dict | None = None,
    actor_context: ActorContext | None = None,
) -> MarcImportRecord:
    actor_context = actor_context or ActorContext()
    with transaction.atomic():
        record = (
            MarcImportRecord.objects.select_for_update()
            .select_related("batch")
            .get(id=import_record_id)
        )
        if record.status != MarcImportRecord.Status.PARSED:
            raise CatalogingError(
                "record_not_approvable", "Only parsed records without conflicts can be approved."
            )
        mapped = _merged_mapping(record.mapped_json, mapped_overrides or {})
        if record.format_type == MarcRecord.FormatType.AUTHORITY:
            marc_record, target = _create_authority_from_import(record, mapped, actor_context)
            link_updates = {"authority_record": target, "marc_record": marc_record}
        elif record.format_type == MarcRecord.FormatType.HOLDINGS:
            marc_record, target = _create_holding_from_import(record, mapped, actor_context)
            link_updates = {"holding": target, "marc_record": marc_record}
        else:
            marc_record, target = _create_bibliographic_from_import(record, mapped)
            link_updates = {"bibliographic_record": target, "marc_record": marc_record}
        before = {"status": record.status}
        record.status = MarcImportRecord.Status.APPROVED
        record.resolution_action = "create_new"
        record.resolved_by = (
            actor_context.actor if getattr(actor_context.actor, "is_authenticated", False) else None
        )
        record.resolved_at = timezone.now()
        for key, value in link_updates.items():
            setattr(record, key, value)
        record.mapped_json = mapped
        record.save(
            update_fields=[
                "status",
                "bibliographic_record",
                "authority_record",
                "holding",
                "marc_record",
                "mapped_json",
                "resolution_action",
                "resolved_by",
                "resolved_at",
                "updated_at",
            ]
        )
        _audit(
            "marc_import_record_approved", record, before, {"status": record.status}, actor_context
        )
        return record


def resolve_import_record(
    *,
    import_record_id,
    action: str,
    target_id=None,
    mapped_overrides: dict | None = None,
    actor_context: ActorContext | None = None,
) -> MarcImportRecord:
    actor_context = actor_context or ActorContext()
    with transaction.atomic():
        record = (
            MarcImportRecord.objects.select_for_update()
            .select_related("batch")
            .get(id=import_record_id)
        )
        if record.status not in [MarcImportRecord.Status.PARSED, MarcImportRecord.Status.CONFLICT]:
            raise CatalogingError(
                "record_not_resolvable", "Only parsed or conflict records can be resolved."
            )
        mapped = _merged_mapping(record.mapped_json, mapped_overrides or {})
        before = {"status": record.status, "resolution_action": record.resolution_action}
        if action == "create_new":
            if record.format_type == MarcRecord.FormatType.AUTHORITY:
                marc_record, target = _create_authority_from_import(record, mapped, actor_context)
                record.authority_record = target
            elif record.format_type == MarcRecord.FormatType.HOLDINGS:
                marc_record, target = _create_holding_from_import(record, mapped, actor_context)
                record.holding = target
            else:
                marc_record, target = _create_bibliographic_from_import(record, mapped)
                record.bibliographic_record = target
        elif action == "link_existing":
            marc_record = _link_existing_from_import(record, mapped, target_id)
        elif action == "overlay_existing":
            marc_record = _overlay_existing_from_import(record, mapped, target_id, actor_context)
        else:
            raise CatalogingError(
                "invalid_resolution_action", f"Unsupported resolution action: {action}"
            )
        record.status = MarcImportRecord.Status.APPROVED
        record.marc_record = marc_record
        record.mapped_json = mapped
        record.resolution_action = action
        record.resolved_by = (
            actor_context.actor if getattr(actor_context.actor, "is_authenticated", False) else None
        )
        record.resolved_at = timezone.now()
        record.match_candidates.update(selected=False)
        if target_id:
            record.match_candidates.filter(target_id=str(target_id)).update(selected=True)
        record.save(
            update_fields=[
                "status",
                "bibliographic_record",
                "authority_record",
                "holding",
                "marc_record",
                "mapped_json",
                "resolution_action",
                "resolved_by",
                "resolved_at",
                "updated_at",
            ]
        )
        _audit(
            "marc_import_record_resolved",
            record,
            before,
            {"status": record.status, "resolution_action": action},
            actor_context,
        )
        return record


def reject_import_record(
    *, import_record_id, note: str = "", actor_context: ActorContext | None = None
) -> MarcImportRecord:
    actor_context = actor_context or ActorContext()
    with transaction.atomic():
        record = MarcImportRecord.objects.select_for_update().get(id=import_record_id)
        if record.status == MarcImportRecord.Status.APPROVED:
            raise CatalogingError("record_already_approved", "Approved records cannot be rejected.")
        before = {"status": record.status}
        record.status = MarcImportRecord.Status.REJECTED
        if note:
            record.validation_errors = [*record.validation_errors, f"Rejected: {note}"]
        record.save(update_fields=["status", "validation_errors", "updated_at"])
        _audit(
            "marc_import_record_rejected", record, before, {"status": record.status}, actor_context
        )
        return record


def generate_authority_suggestions(
    *, import_record: MarcImportRecord
) -> list[AuthorityLinkSuggestion]:
    import_record.authority_suggestions.all().delete()
    suggestions = []
    for tag, authority_type, role in _authority_field_specs():
        for label in _field_values(import_record.parsed_json, tag, "a"):
            normalized = label.rstrip(" .,")
            if not normalized:
                continue
            match = (
                AuthorityRecord.objects.filter(access_points__label__iexact=normalized)
                .distinct()
                .first()
            )
            suggestions.append(
                AuthorityLinkSuggestion.objects.create(
                    import_record=import_record,
                    marc_tag=tag,
                    label=normalized,
                    authority_type=authority_type,
                    role=role,
                    matched_authority=match,
                    confidence=100 if match else 0,
                )
            )
    return suggestions


def accept_authority_suggestion(
    *, suggestion_id, authority_id, actor_context: ActorContext | None = None
) -> AuthorityLinkSuggestion:
    actor_context = actor_context or ActorContext()
    with transaction.atomic():
        suggestion = (
            AuthorityLinkSuggestion.objects.select_for_update()
            .select_related("import_record", "import_record__bibliographic_record")
            .get(id=suggestion_id)
        )
        authority = AuthorityRecord.objects.get(id=authority_id)
        bib = suggestion.import_record.bibliographic_record
        if not bib:
            raise CatalogingError(
                "record_not_approved",
                "Authority suggestions can be accepted after record approval.",
            )
        if suggestion.role == "creator" or suggestion.authority_type in [
            AuthorityRecord.AuthorityType.SUBJECT,
            AuthorityRecord.AuthorityType.GENRE,
            AuthorityRecord.AuthorityType.PLACE,
            AuthorityRecord.AuthorityType.WORK_TITLE,
        ]:
            WorkAuthorityLink.objects.get_or_create(
                work=bib.work,
                authority=authority,
                role=WorkAuthorityLink.Role.SUBJECT
                if suggestion.role == "subject"
                else WorkAuthorityLink.Role.CREATOR,
                relationship_designator=suggestion.role,
            )
        else:
            InstanceContributor.objects.get_or_create(
                instance=bib.instance,
                authority=authority,
                role=suggestion.role,
                marc_tag=suggestion.marc_tag,
            )
        before = {"status": suggestion.status}
        suggestion.matched_authority = authority
        suggestion.status = AuthorityLinkSuggestion.Status.ACCEPTED
        suggestion.save(update_fields=["matched_authority", "status", "updated_at"])
        _audit(
            "authority_suggestion_accepted",
            suggestion,
            before,
            {"status": suggestion.status},
            actor_context,
        )
        return suggestion


def reject_authority_suggestion(
    *, suggestion_id, note: str = "", actor_context: ActorContext | None = None
):
    actor_context = actor_context or ActorContext()
    with transaction.atomic():
        suggestion = AuthorityLinkSuggestion.objects.select_for_update().get(id=suggestion_id)
        before = {"status": suggestion.status}
        suggestion.status = AuthorityLinkSuggestion.Status.REJECTED
        suggestion.note = note
        suggestion.save(update_fields=["status", "note", "updated_at"])
        _audit(
            "authority_suggestion_rejected",
            suggestion,
            before,
            {"status": suggestion.status},
            actor_context,
        )
        return suggestion


def create_provisional_authority_from_suggestion(
    *, suggestion_id, actor_context: ActorContext | None = None
) -> AuthorityLinkSuggestion:
    actor_context = actor_context or ActorContext()
    with transaction.atomic():
        suggestion = AuthorityLinkSuggestion.objects.select_for_update().get(id=suggestion_id)
        authority = AuthorityRecord.objects.create(
            authority_type=suggestion.authority_type,
            source="local",
            status=AuthorityRecord.Status.PROVISIONAL,
            metadata={"created_from_marc_import_suggestion": str(suggestion.id)},
        )
        AccessPoint.objects.create(
            authority=authority,
            kind=AccessPoint.Kind.AUTHORIZED,
            label=suggestion.label,
            source_field=suggestion.marc_tag,
            is_preferred=True,
        )
        before = {"status": suggestion.status}
        suggestion.matched_authority = authority
        suggestion.status = AuthorityLinkSuggestion.Status.CREATED
        suggestion.save(update_fields=["matched_authority", "status", "updated_at"])
        _audit(
            "authority_suggestion_created_provisional",
            suggestion,
            before,
            {"status": suggestion.status},
            actor_context,
        )
        return suggestion


def _split_raw_records(payload: bytes | str, import_format: str) -> list[str]:
    text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
    if import_format == MarcImportBatch.ImportFormat.ISO2709:
        return [record + "\x1d" for record in text.split("\x1d") if record]
    if import_format == MarcImportBatch.ImportFormat.JSON:
        loaded = json.loads(text)
        items = loaded if isinstance(loaded, list) else loaded.get("records", [loaded])
        return [json.dumps(item, ensure_ascii=False) for item in items]
    if import_format == MarcImportBatch.ImportFormat.MARCXML:
        root = ET.fromstring(text)
        nodes = (
            [root]
            if root.tag.rsplit("}", 1)[-1] == "record"
            else [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "record"]
        )
        return [ET.tostring(node, encoding="unicode") for node in nodes]
    raise CatalogingError(
        "unsupported_import_format", f"Unsupported import format: {import_format}"
    )


def _parse_import_record(record: MarcImportRecord, batch: MarcImportBatch) -> None:
    try:
        parsed = parse_records(record.raw_payload, batch.import_format)[0]["parsed"]
        validation_errors = validate_parsed_record(parsed)
        mapped = map_record(parsed)
        format_type = _format_type_from_mapping(mapped)
        conflict_reason = _detect_conflict(batch.source, mapped, format_type)
        record.parsed_json = parsed
        record.mapped_json = mapped
        record.format_type = format_type
        record.validation_errors = validation_errors
        record.control_number = mapped.get("control_number", "")
        record.conflict_reason = conflict_reason
        record.match_candidates.all().delete()
        _create_match_candidates(
            record=record, source=batch.source, mapped=mapped, format_type=format_type
        )
        if validation_errors:
            record.status = MarcImportRecord.Status.INVALID
        elif conflict_reason:
            record.status = MarcImportRecord.Status.CONFLICT
        else:
            record.status = MarcImportRecord.Status.PARSED
    except (MarcParseError, ValueError, KeyError) as exc:
        record.validation_errors = [str(exc)]
        record.status = MarcImportRecord.Status.INVALID
    record.save(
        update_fields=[
            "parsed_json",
            "mapped_json",
            "format_type",
            "validation_errors",
            "status",
            "control_number",
            "conflict_reason",
            "updated_at",
        ]
    )


def _format_type_from_mapping(mapped: dict) -> str:
    if "authority" in mapped:
        return MarcRecord.FormatType.AUTHORITY
    if "holding" in mapped:
        return MarcRecord.FormatType.HOLDINGS
    return MarcRecord.FormatType.BIBLIOGRAPHIC


def _detect_conflict(source: str, mapped: dict, format_type: str) -> str:
    if format_type == MarcRecord.FormatType.AUTHORITY:
        label = mapped.get("authority", {}).get("preferred_label", "")
        if label and AuthorityRecord.objects.filter(access_points__label__iexact=label).exists():
            return f"Existing authority heading {label}"
        control_number = mapped.get("control_number", "")
        if (
            control_number
            and AuthorityRecord.objects.filter(
                source=source, control_number=control_number
            ).exists()
        ):
            return f"Existing authority record with source/control number {source}:{control_number}"
        return ""
    if format_type == MarcRecord.FormatType.HOLDINGS:
        holding = mapped.get("holding", {})
        bib_control = mapped.get("bibliographic_control_number", "")
        if not BibliographicRecord.objects.filter(control_number=bib_control).exists():
            return f"Bibliographic control number not found: {bib_control}"
        branch = Branch.objects.filter(code=holding.get("branch_code", "")).first()
        if not branch:
            return f"Branch not found: {holding.get('branch_code', '')}"
        if not Location.objects.filter(
            branch=branch, code=holding.get("location_code", "")
        ).exists():
            return f"Location not found: {holding.get('location_code', '')}"
        return ""
    control_number = mapped.get("control_number", "")
    if (
        control_number
        and BibliographicRecord.objects.filter(
            source=source, control_number=control_number
        ).exists()
    ):
        return f"Existing bibliographic record with source/control number {source}:{control_number}"
    identifiers = mapped.get("instance", {}).get("identifiers", [])
    for identifier in identifiers:
        for instance in Instance.objects.exclude(identifiers=[]).only("id", "identifiers"):
            if identifier in instance.identifiers:
                return f"Existing instance with {identifier['scheme']} {identifier['value']}"
    return ""


def _create_match_candidates(
    *, record: MarcImportRecord, source: str, mapped: dict, format_type: str
) -> None:
    if format_type == MarcRecord.FormatType.AUTHORITY:
        _authority_candidates(record, source, mapped)
    elif format_type == MarcRecord.FormatType.HOLDINGS:
        _holdings_candidates(record, mapped)
    else:
        _bibliographic_candidates(record, source, mapped)


def _bibliographic_candidates(record: MarcImportRecord, source: str, mapped: dict) -> None:
    control_number = mapped.get("control_number", "")
    if control_number:
        for bib in BibliographicRecord.objects.filter(source=source, control_number=control_number):
            _candidate(
                record,
                MarcMatchCandidate.TargetType.BIBLIOGRAPHIC,
                bib.id,
                "source_control_number",
                100,
                f"Same source/control number {source}:{control_number}",
                {"title": bib.instance.title_statement if bib.instance else ""},
            )
    for identifier in mapped.get("instance", {}).get("identifiers", []):
        for instance in Instance.objects.exclude(identifiers=[]).only(
            "id", "title_statement", "identifiers"
        ):
            if identifier in instance.identifiers:
                _candidate(
                    record,
                    MarcMatchCandidate.TargetType.INSTANCE,
                    instance.id,
                    "identifier",
                    95,
                    f"Same {identifier.get('scheme')} {identifier.get('value')}",
                    {"title": instance.title_statement},
                )
    title = mapped.get("instance", {}).get("title_statement", "")
    publisher = mapped.get("instance", {}).get("publisher", "")
    date = mapped.get("instance", {}).get("publication_date", "")
    if title:
        matches = Instance.objects.filter(title_statement__iexact=title)
        if publisher:
            matches = matches.filter(publisher__iexact=publisher)
        if date:
            matches = matches.filter(publication_date__icontains=date[:4])
        for instance in matches[:10]:
            _candidate(
                record,
                MarcMatchCandidate.TargetType.INSTANCE,
                instance.id,
                "title_publisher_date",
                80,
                "Similar title/publisher/date",
                {"title": instance.title_statement, "publisher": instance.publisher},
            )


def _authority_candidates(record: MarcImportRecord, source: str, mapped: dict) -> None:
    control_number = mapped.get("control_number", "")
    if control_number:
        for authority in AuthorityRecord.objects.filter(
            source=source, control_number=control_number
        ):
            _candidate(
                record,
                MarcMatchCandidate.TargetType.AUTHORITY,
                authority.id,
                "source_control_number",
                100,
                f"Same source/control number {source}:{control_number}",
                {"label": str(authority)},
            )
    label = mapped.get("authority", {}).get("preferred_label", "")
    if label:
        for authority in AuthorityRecord.objects.filter(
            access_points__label__iexact=label
        ).distinct():
            _candidate(
                record,
                MarcMatchCandidate.TargetType.AUTHORITY,
                authority.id,
                "heading_exact",
                95,
                f"Same authority heading {label}",
                {"label": str(authority)},
            )


def _holdings_candidates(record: MarcImportRecord, mapped: dict) -> None:
    bib_control = mapped.get("bibliographic_control_number", "")
    holding_data = mapped.get("holding", {})
    bibs = BibliographicRecord.objects.filter(control_number=bib_control).select_related("instance")
    for bib in bibs:
        _candidate(
            record,
            MarcMatchCandidate.TargetType.BIBLIOGRAPHIC,
            bib.id,
            "004_bibliographic_control_number",
            90,
            f"Linked bibliographic control number {bib_control}",
            {"title": bib.instance.title_statement if bib.instance else ""},
        )
        branch = Branch.objects.filter(code=holding_data.get("branch_code", "")).first()
        location = (
            Location.objects.filter(
                branch=branch, code=holding_data.get("location_code", "")
            ).first()
            if branch
            else None
        )
        if bib.instance and branch and location:
            for holding in Holding.objects.filter(
                instance=bib.instance, branch=branch, location=location
            ):
                _candidate(
                    record,
                    MarcMatchCandidate.TargetType.HOLDING,
                    holding.id,
                    "same_instance_branch_location",
                    85,
                    "Same instance, branch and location",
                    {"textual_holdings": holding.textual_holdings},
                )


def _candidate(
    record: MarcImportRecord,
    target_type: str,
    target_id,
    match_rule: str,
    confidence: int,
    reason: str,
    payload: dict,
) -> None:
    MarcMatchCandidate.objects.get_or_create(
        import_record=record,
        target_type=target_type,
        target_id=str(target_id),
        match_rule=match_rule,
        defaults={"confidence": confidence, "reason": reason, "payload": payload},
    )


def _create_bibliographic_from_import(
    record: MarcImportRecord, mapped: dict
) -> tuple[MarcRecord, BibliographicRecord]:
    work = Work.objects.create(**mapped["work"])
    instance = Instance.objects.create(work=work, **mapped["instance"])
    bib = BibliographicRecord.objects.create(
        source=record.batch.source,
        control_number=mapped["control_number"],
        encoding_level=record.parsed_json.get("leader", "")[17:18],
        status=BibliographicRecord.Status.APPROVED,
        work=work,
        instance=instance,
        metadata=_bib_metadata(mapped),
    )
    return _create_marc_record(record, mapped, bibliographic_record=bib), bib


def _create_authority_from_import(
    record: MarcImportRecord, mapped: dict, actor_context: ActorContext
) -> tuple[MarcRecord, AuthorityRecord]:
    authority_data = mapped.get("authority", {})
    authority = AuthorityRecord.objects.create(
        authority_type=authority_data.get("authority_type", AuthorityRecord.AuthorityType.SUBJECT),
        source=record.batch.source,
        control_number=mapped.get("control_number", ""),
        status=authority_data.get("status", AuthorityRecord.Status.AUTHORIZED),
        metadata={
            "agency": mapped.get("agency", ""),
            "notes": mapped.get("notes", []),
            "related_headings": mapped.get("related_headings", []),
        },
    )
    _access_point(
        authority=authority,
        kind=AccessPoint.Kind.AUTHORIZED,
        label=authority_data.get("preferred_label", "[untitled authority]"),
        source_field=authority_data.get("source_field", ""),
        is_preferred=True,
    )
    for variant in mapped.get("variants", []):
        _access_point(
            authority=authority,
            kind=AccessPoint.Kind.VARIANT,
            label=variant.get("label", ""),
            source_field=variant.get("source_field", ""),
            language=variant.get("language", ""),
        )
    for identifier in mapped.get("external_identifiers", []):
        if identifier.get("value"):
            ExternalIdentifier.objects.get_or_create(
                scheme=identifier.get("scheme", ""),
                value=identifier.get("value", ""),
                defaults={"authority": authority, "uri": identifier.get("uri", "")},
            )
    _audit(
        "marc_authority_imported",
        authority,
        {},
        {"preferred_label": authority_data.get("preferred_label", "")},
        actor_context,
    )
    return _create_marc_record(record, mapped, authority_record=authority), authority


def _create_holding_from_import(
    record: MarcImportRecord, mapped: dict, actor_context: ActorContext
) -> tuple[MarcRecord, Holding]:
    holding_data = mapped.get("holding", {})
    bib = _bib_for_holdings(mapped)
    branch = _branch_for_holdings(holding_data)
    location = _location_for_holdings(branch, holding_data)
    call_number = _call_number(holding_data.get("call_number", ""))
    holding, _ = Holding.objects.get_or_create(
        instance=bib.instance,
        branch=branch,
        location=location,
        defaults={
            "call_number": call_number,
            "public_note": holding_data.get("public_note", ""),
            "staff_note": holding_data.get("staff_note", ""),
            "textual_holdings": holding_data.get("textual_holdings", ""),
        },
    )
    changed = False
    for field in ["public_note", "staff_note", "textual_holdings"]:
        if holding_data.get(field) and getattr(holding, field) != holding_data[field]:
            setattr(holding, field, holding_data[field])
            changed = True
    if call_number and holding.call_number_id != call_number.id:
        holding.call_number = call_number
        changed = True
    if changed:
        holding.save()
    for item_data in mapped.get("items", []):
        barcode = item_data.get("barcode", "")
        if not barcode:
            continue
        Item.objects.get_or_create(
            barcode=barcode,
            defaults={
                "holding": holding,
                "copy_number": item_data.get("copy_number", ""),
                "status": item_data.get("status", Item.Status.IN_PROCESS),
                "item_note": item_data.get("item_note", ""),
            },
        )
    _audit(
        "marc_holdings_imported",
        holding,
        {},
        {"control_number": mapped.get("control_number", "")},
        actor_context,
    )
    return _create_marc_record(record, mapped, holding=holding, bibliographic_record=bib), holding


def _link_existing_from_import(record: MarcImportRecord, mapped: dict, target_id) -> MarcRecord:
    if not target_id:
        raise CatalogingError("target_required", "target_id is required for link_existing.")
    if record.format_type == MarcRecord.FormatType.AUTHORITY:
        authority = AuthorityRecord.objects.get(id=target_id)
        record.authority_record = authority
        return _create_marc_record(record, mapped, authority_record=authority)
    if record.format_type == MarcRecord.FormatType.HOLDINGS:
        holding = Holding.objects.select_related("instance").get(id=target_id)
        bib = BibliographicRecord.objects.filter(instance=holding.instance).first()
        record.holding = holding
        return _create_marc_record(record, mapped, holding=holding, bibliographic_record=bib)
    target = _bibliographic_target(target_id)
    record.bibliographic_record = target
    return _create_marc_record(record, mapped, bibliographic_record=target)


def _overlay_existing_from_import(
    record: MarcImportRecord, mapped: dict, target_id, actor_context: ActorContext
) -> MarcRecord:
    if not target_id:
        raise CatalogingError("target_required", "target_id is required for overlay_existing.")
    if record.format_type == MarcRecord.FormatType.AUTHORITY:
        authority = AuthorityRecord.objects.select_for_update().get(id=target_id)
        before = {"metadata": authority.metadata}
        authority.control_number = authority.control_number or mapped.get("control_number", "")
        authority.metadata = {**authority.metadata, "marc_overlay": mapped}
        authority.save(update_fields=["control_number", "metadata", "updated_at"])
        for variant in mapped.get("variants", []):
            if variant.get("label"):
                _access_point(
                    authority=authority,
                    kind=AccessPoint.Kind.VARIANT,
                    label=variant["label"],
                    source_field=variant.get("source_field", ""),
                    language=variant.get("language", ""),
                )
        _audit(
            "marc_authority_overlay",
            authority,
            before,
            {"metadata": authority.metadata},
            actor_context,
        )
        record.authority_record = authority
        return _create_marc_record(record, mapped, authority_record=authority)
    if record.format_type == MarcRecord.FormatType.HOLDINGS:
        holding = Holding.objects.select_for_update().get(id=target_id)
        before = {
            "public_note": holding.public_note,
            "staff_note": holding.staff_note,
            "textual_holdings": holding.textual_holdings,
        }
        holding_data = mapped.get("holding", {})
        for field in ["public_note", "staff_note", "textual_holdings"]:
            if holding_data.get(field):
                setattr(holding, field, holding_data[field])
        holding.save()
        _audit("marc_holdings_overlay", holding, before, holding_data, actor_context)
        record.holding = holding
        bib = BibliographicRecord.objects.filter(instance=holding.instance).first()
        return _create_marc_record(record, mapped, holding=holding, bibliographic_record=bib)
    bib = _bibliographic_target(target_id)
    before = {"metadata": bib.metadata}
    _apply_bibliographic_overlay(bib, mapped)
    _audit("marc_bibliographic_overlay", bib, before, {"metadata": bib.metadata}, actor_context)
    record.bibliographic_record = bib
    return _create_marc_record(record, mapped, bibliographic_record=bib)


def merge_bibliographic_records(
    *, source_id, target_id, note: str = "", actor_context: ActorContext | None = None
) -> BibliographicRecord:
    actor_context = actor_context or ActorContext()
    if str(source_id) == str(target_id):
        raise CatalogingError("same_bibliographic_record", "Source and target must be different.")
    with transaction.atomic():
        source = BibliographicRecord.objects.select_for_update().get(id=source_id)
        target = BibliographicRecord.objects.select_for_update().get(id=target_id)
        before = {"source_status": source.status, "target": str(target.id)}
        Holding.objects.filter(instance=source.instance).update(instance=target.instance)
        MarcRecord.objects.filter(bibliographic_record=source).update(bibliographic_record=target)
        MarcImportRecord.objects.filter(bibliographic_record=source).update(
            bibliographic_record=target
        )
        source.status = BibliographicRecord.Status.SUPPRESSED
        source.metadata = {**source.metadata, "merged_into": str(target.id), "merge_note": note}
        source.save(update_fields=["status", "metadata", "updated_at"])
        _audit(
            "bibliographic_records_merged",
            source,
            before,
            {"source_status": source.status, "target": str(target.id)},
            actor_context,
        )
        return target


def _create_marc_record(
    record: MarcImportRecord,
    mapped: dict,
    *,
    bibliographic_record: BibliographicRecord | None = None,
    authority_record: AuthorityRecord | None = None,
    holding: Holding | None = None,
) -> MarcRecord:
    return MarcRecord.objects.create(
        bibliographic_record=bibliographic_record,
        authority_record=authority_record,
        holding=holding,
        format_type=record.format_type,
        raw_iso2709=record.raw_payload.encode("utf-8", errors="replace")
        if record.batch.import_format == MarcImportBatch.ImportFormat.ISO2709
        else None,
        marcxml=record.raw_payload
        if record.batch.import_format == MarcImportBatch.ImportFormat.MARCXML
        else "",
        parsed_json=record.parsed_json,
        leader=record.parsed_json.get("leader", ""),
        control_number=mapped.get("control_number", ""),
        source=record.batch.source,
        validation_status=MarcRecord.ValidationStatus.VALID,
        imported_at=timezone.now(),
    )


def _bib_metadata(mapped: dict) -> dict:
    return {
        "agency": mapped.get("agency", ""),
        "fixed_field_008": mapped.get("fixed_field_008", ""),
        "subjects": mapped.get("subjects", []),
        "contributors": mapped.get("contributors", []),
        "classifications": mapped.get("classifications", []),
    }


def _apply_bibliographic_overlay(bib: BibliographicRecord, mapped: dict) -> None:
    if bib.work and mapped.get("work"):
        for key, value in mapped["work"].items():
            setattr(bib.work, key, value)
        bib.work.save()
    if bib.instance and mapped.get("instance"):
        for key, value in mapped["instance"].items():
            setattr(bib.instance, key, value)
        bib.instance.save()
    bib.control_number = bib.control_number or mapped.get("control_number", "")
    bib.metadata = {
        **bib.metadata,
        **_bib_metadata(mapped),
        "marc_overlay_at": timezone.now().isoformat(),
    }
    bib.save(update_fields=["control_number", "metadata", "updated_at"])


def _bibliographic_target(target_id) -> BibliographicRecord:
    bib = BibliographicRecord.objects.filter(id=target_id).first()
    if bib:
        return bib
    instance = Instance.objects.filter(id=target_id).first()
    if instance:
        bib = BibliographicRecord.objects.filter(instance=instance).first()
        if bib:
            return bib
    raise CatalogingError(
        "target_not_found", "Target bibliographic record or instance was not found."
    )


def _bib_for_holdings(mapped: dict) -> BibliographicRecord:
    control_number = mapped.get("bibliographic_control_number", "")
    bib = (
        BibliographicRecord.objects.filter(control_number=control_number)
        .select_related("instance")
        .first()
    )
    if not bib or not bib.instance:
        raise CatalogingError(
            "bibliographic_not_found", f"Bibliographic record not found: {control_number}"
        )
    return bib


def _branch_for_holdings(holding_data: dict) -> Branch:
    branch = Branch.objects.filter(code=holding_data.get("branch_code", "")).first()
    if not branch:
        raise CatalogingError(
            "branch_not_found", f"Branch not found: {holding_data.get('branch_code', '')}"
        )
    return branch


def _location_for_holdings(branch: Branch, holding_data: dict) -> Location:
    location = Location.objects.filter(
        branch=branch, code=holding_data.get("location_code", "")
    ).first()
    if not location:
        raise CatalogingError(
            "location_not_found", f"Location not found: {holding_data.get('location_code', '')}"
        )
    return location


def _call_number(raw: str) -> CallNumber | None:
    if not raw:
        return None
    call_number, _ = CallNumber.objects.get_or_create(
        raw=raw,
        defaults={"normalized_sort_key": raw.upper()},
    )
    return call_number


def _access_point(
    *,
    authority: AuthorityRecord,
    kind: str,
    label: str,
    source_field: str = "",
    language: str = "",
    is_preferred: bool = False,
) -> AccessPoint:
    if not label:
        label = "[blank heading]"
    existing = authority.access_points.filter(label__iexact=label, kind=kind).first()
    if existing:
        return existing
    return AccessPoint.objects.create(
        authority=authority,
        kind=kind,
        label=label,
        normalized_label=label.casefold(),
        sort_key=label.casefold(),
        language=language,
        source_field=source_field,
        is_preferred=is_preferred,
    )


def _merged_mapping(mapped: dict, overrides: dict) -> dict:
    merged = {
        **mapped,
        "work": {**mapped.get("work", {}), **overrides.get("work", {})},
        "instance": {**mapped.get("instance", {}), **overrides.get("instance", {})},
        "authority": {**mapped.get("authority", {}), **overrides.get("authority", {})},
        "holding": {**mapped.get("holding", {}), **overrides.get("holding", {})},
    }
    return merged


def _authority_field_specs():
    return [
        ("100", AuthorityRecord.AuthorityType.PERSON, "creator"),
        ("110", AuthorityRecord.AuthorityType.CORPORATE_BODY, "creator"),
        ("111", AuthorityRecord.AuthorityType.CONFERENCE, "creator"),
        ("700", AuthorityRecord.AuthorityType.PERSON, "contributor"),
        ("710", AuthorityRecord.AuthorityType.CORPORATE_BODY, "contributor"),
        ("711", AuthorityRecord.AuthorityType.CONFERENCE, "contributor"),
        ("600", AuthorityRecord.AuthorityType.PERSON, "subject"),
        ("610", AuthorityRecord.AuthorityType.CORPORATE_BODY, "subject"),
        ("611", AuthorityRecord.AuthorityType.CONFERENCE, "subject"),
        ("630", AuthorityRecord.AuthorityType.WORK_TITLE, "subject"),
        ("650", AuthorityRecord.AuthorityType.SUBJECT, "subject"),
        ("651", AuthorityRecord.AuthorityType.PLACE, "subject"),
        ("655", AuthorityRecord.AuthorityType.GENRE, "subject"),
    ]


def _field_values(parsed: dict, tag: str, code: str) -> list[str]:
    values = []
    for field in parsed.get("fields", []):
        if field.get("tag") != tag:
            continue
        values.extend(
            subfield.get("value", "")
            for subfield in field.get("subfields", [])
            if subfield.get("code") == code
        )
    return values


def _audit(action: str, entity, before: dict, after: dict, actor_context: ActorContext) -> None:
    AuditLog.objects.create(
        actor=actor_context.actor
        if getattr(actor_context.actor, "is_authenticated", False)
        else None,
        action=action,
        entity_type=ContentType.objects.get_for_model(entity.__class__),
        entity_id=str(entity.id),
        before=before,
        after=after,
        ip_address=actor_context.ip_address,
        user_agent=actor_context.user_agent,
    )
