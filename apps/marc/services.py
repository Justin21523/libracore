from __future__ import annotations

from django.utils import timezone

from apps.catalog.models import BibliographicRecord, Instance, Work
from apps.marc.mapping import map_bibliographic_record
from apps.marc.models import MarcRecord
from apps.marc.parser import MarcParseError, parse_iso2709, validate_parsed_record


def import_bibliographic_iso2709(raw: bytes, source: str = "") -> MarcRecord:
    try:
        parsed = parse_iso2709(raw)
        validation_errors = validate_parsed_record(parsed)
    except MarcParseError as exc:
        return MarcRecord.objects.create(
            format_type=MarcRecord.FormatType.BIBLIOGRAPHIC,
            raw_iso2709=raw,
            source=source,
            validation_status=MarcRecord.ValidationStatus.INVALID,
            validation_errors=[str(exc)],
            imported_at=timezone.now(),
        )

    mapped = map_bibliographic_record(parsed)
    work = Work.objects.create(**mapped["work"])
    instance = Instance.objects.create(work=work, **mapped["instance"])
    bib = BibliographicRecord.objects.create(
        source=source,
        control_number=mapped["control_number"],
        encoding_level=parsed["leader"][17:18],
        work=work,
        instance=instance,
        metadata={
            "agency": mapped["agency"],
            "fixed_field_008": mapped["fixed_field_008"],
            "subjects": mapped["subjects"],
            "contributors": mapped["contributors"],
            "classifications": mapped["classifications"],
        },
    )
    return MarcRecord.objects.create(
        bibliographic_record=bib,
        format_type=MarcRecord.FormatType.BIBLIOGRAPHIC,
        raw_iso2709=raw,
        parsed_json=parsed,
        leader=parsed["leader"],
        control_number=mapped["control_number"],
        source=source,
        validation_status=(
            MarcRecord.ValidationStatus.INVALID if validation_errors else MarcRecord.ValidationStatus.VALID
        ),
        validation_errors=validation_errors,
        imported_at=timezone.now(),
    )

