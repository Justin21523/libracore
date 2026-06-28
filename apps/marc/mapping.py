from __future__ import annotations

from apps.marc.parser import field_values, first_field_value


def detect_format_type(parsed: dict) -> str:
    leader = parsed.get("leader", "")
    record_type = leader[6:7]
    if record_type == "z":
        return "authority"
    if record_type in {"u", "v", "x", "y"}:
        return "holdings"
    return "bibliographic"


def map_record(parsed: dict) -> dict:
    format_type = detect_format_type(parsed)
    if format_type == "authority":
        return map_authority_record(parsed)
    if format_type == "holdings":
        return map_holdings_record(parsed)
    return map_bibliographic_record(parsed)


def map_bibliographic_record(parsed: dict) -> dict:
    title = first_field_value(parsed, "245", "a").rstrip(" /:")
    responsibility = first_field_value(parsed, "245", "c").rstrip(" /")
    variant_titles = [value.rstrip(" /:") for value in field_values(parsed, "246", "a")]
    publisher_264 = first_field_value(parsed, "264", "b")
    publisher_260 = first_field_value(parsed, "260", "b")
    date_264 = first_field_value(parsed, "264", "c")
    date_260 = first_field_value(parsed, "260", "c")

    identifiers = []
    for value in field_values(parsed, "020", "a"):
        identifiers.append({"scheme": "isbn", "value": value})
    for value in field_values(parsed, "022", "a"):
        identifiers.append({"scheme": "issn", "value": value})

    subjects = []
    for tag in ["600", "610", "611", "630", "650", "651", "655"]:
        for value in field_values(parsed, tag, "a"):
            subjects.append({"marc_tag": tag, "label": value.rstrip(".")})

    notes = []
    for tag in ["500", "504", "505", "520", "546", "588"]:
        for value in field_values(parsed, tag, "a"):
            notes.append({"marc_tag": tag, "value": value})

    contributors = []
    for tag in ["100", "110", "111", "700", "710", "711"]:
        for value in field_values(parsed, tag, "a"):
            contributors.append({"marc_tag": tag, "label": value.rstrip(".")})

    classifications = []
    for tag, scheme in [("050", "lcc"), ("082", "ddc"), ("084", "other")]:
        for value in field_values(parsed, tag, "a"):
            classifications.append({"scheme": scheme, "number": value})

    return {
        "leader": parsed.get("leader", ""),
        "control_number": first_field_value(parsed, "001"),
        "agency": first_field_value(parsed, "003"),
        "fixed_field_008": first_field_value(parsed, "008"),
        "work": {
            "primary_title": title,
            "language_hint": _language_from_008(first_field_value(parsed, "008")),
        },
        "instance": {
            "title_statement": title or "[untitled]",
            "responsibility_statement": responsibility,
            "variant_titles": variant_titles,
            "edition_statement": first_field_value(parsed, "250", "a"),
            "publication_place": first_field_value(parsed, "264", "a")
            or first_field_value(parsed, "260", "a"),
            "publisher": (publisher_264 or publisher_260).rstrip(","),
            "publication_date": (date_264 or date_260).rstrip(".,"),
            "extent": first_field_value(parsed, "300", "a"),
            "content_type": first_field_value(parsed, "336", "a"),
            "media_type": first_field_value(parsed, "337", "a"),
            "carrier_type": first_field_value(parsed, "338", "a"),
            "identifiers": identifiers,
            "notes": notes,
        },
        "contributors": contributors,
        "subjects": subjects,
        "classifications": classifications,
    }


def map_authority_record(parsed: dict) -> dict:
    authorized_field = _first_data_field(parsed, ["100", "110", "111", "130", "150", "151", "155"])
    authority_type = _authority_type_for_tag(
        authorized_field.get("tag", "") if authorized_field else ""
    )
    preferred_label = _heading_label(authorized_field) if authorized_field else ""
    variants = []
    for field in _data_fields(parsed, ["400", "410", "411", "430", "450", "451", "455"]):
        label = _heading_label(field)
        if label:
            variants.append(
                {
                    "label": label,
                    "source_field": field.get("tag", ""),
                    "language": first_field_value(parsed, "377", "a"),
                }
            )
    related = []
    for field in _data_fields(parsed, ["500", "510", "511", "530", "550", "551", "555"]):
        label = _heading_label(field)
        if label:
            related.append({"label": label, "source_field": field.get("tag", "")})
    external_identifiers = []
    for value in field_values(parsed, "010", "a"):
        external_identifiers.append({"scheme": "lccn", "value": value.strip()})
    for value in field_values(parsed, "024", "a"):
        external_identifiers.append({"scheme": "uri", "value": value.strip()})
    for value in field_values(parsed, "035", "a"):
        external_identifiers.append({"scheme": "system_control_number", "value": value.strip()})
    return {
        "leader": parsed.get("leader", ""),
        "control_number": first_field_value(parsed, "001"),
        "agency": first_field_value(parsed, "003"),
        "authority": {
            "authority_type": authority_type,
            "preferred_label": preferred_label or "[untitled authority]",
            "source_field": authorized_field.get("tag", "") if authorized_field else "",
            "status": "authorized",
            "language": first_field_value(parsed, "377", "a"),
        },
        "variants": variants,
        "related_headings": related,
        "external_identifiers": external_identifiers,
        "notes": [
            {"marc_tag": "667", "value": value} for value in field_values(parsed, "667", "a")
        ],
    }


def map_holdings_record(parsed: dict) -> dict:
    location = _first_data_field(parsed, ["852"]) or {}
    item_fields = _data_fields(parsed, ["876"])
    items = []
    for field in item_fields:
        barcode = _subfield(field, "p") or _subfield(field, "a")
        if not barcode:
            continue
        items.append(
            {
                "barcode": barcode,
                "copy_number": _subfield(field, "t"),
                "status": _item_status_from_876(_subfield(field, "j")),
                "item_note": _subfield(field, "z") or _subfield(field, "x"),
            }
        )
    textual_holdings = []
    for tag in ["866", "867", "868"]:
        for value in field_values(parsed, tag, "a"):
            textual_holdings.append({"marc_tag": tag, "value": value})
    call_parts = [
        _subfield(location, "h"),
        _subfield(location, "i"),
        _subfield(location, "m"),
        _subfield(location, "t"),
    ]
    call_number = " ".join(part for part in call_parts if part).strip()
    return {
        "leader": parsed.get("leader", ""),
        "control_number": first_field_value(parsed, "001"),
        "bibliographic_control_number": first_field_value(parsed, "004"),
        "agency": first_field_value(parsed, "003"),
        "holding": {
            "branch_code": _subfield(location, "b"),
            "location_code": _subfield(location, "c"),
            "call_number": call_number,
            "public_note": _subfield(location, "z"),
            "staff_note": _subfield(location, "x"),
            "textual_holdings": "; ".join(item["value"] for item in textual_holdings),
        },
        "items": items,
        "textual_holdings": textual_holdings,
    }


def _language_from_008(value: str) -> str:
    return value[35:38].strip() if len(value) >= 38 else ""


def _data_fields(parsed: dict, tags: list[str]) -> list[dict]:
    return [
        field
        for field in parsed.get("fields", [])
        if field.get("tag") in tags and "subfields" in field
    ]


def _first_data_field(parsed: dict, tags: list[str]) -> dict | None:
    fields = _data_fields(parsed, tags)
    return fields[0] if fields else None


def _subfield(field: dict, code: str) -> str:
    for subfield in field.get("subfields", []):
        if subfield.get("code") == code:
            return subfield.get("value", "").strip(" .,;:/")
    return ""


def _heading_label(field: dict | None) -> str:
    if not field:
        return ""
    pieces = [
        subfield.get("value", "").strip()
        for subfield in field.get("subfields", [])
        if subfield.get("code") in {"a", "b", "c", "d", "q", "t", "v", "x", "y", "z"}
    ]
    return " ".join(piece for piece in pieces if piece).rstrip(" .,")


def _authority_type_for_tag(tag: str) -> str:
    return {
        "100": "person",
        "400": "person",
        "110": "corporate_body",
        "410": "corporate_body",
        "111": "conference",
        "411": "conference",
        "130": "work_title",
        "430": "work_title",
        "150": "subject",
        "450": "subject",
        "151": "place",
        "451": "place",
        "155": "genre",
        "455": "genre",
    }.get(tag, "subject")


def _item_status_from_876(value: str) -> str:
    normalized = (value or "").lower()
    if normalized in {
        "available",
        "on_loan",
        "on_hold",
        "in_process",
        "missing",
        "lost",
        "withdrawn",
    }:
        return normalized
    if normalized in {"-", "0", ""}:
        return "available"
    return "in_process"
