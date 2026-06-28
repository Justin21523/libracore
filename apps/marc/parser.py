from __future__ import annotations

FIELD_TERMINATOR = "\x1e"
RECORD_TERMINATOR = "\x1d"
SUBFIELD_DELIMITER = "\x1f"


class MarcParseError(ValueError):
    pass


def parse_iso2709(raw: bytes | str) -> dict:
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
    if len(text) < 25:
        raise MarcParseError("MARC record is too short to contain a valid leader and directory")

    leader = text[:24]
    try:
        base_address = int(leader[12:17])
    except ValueError as exc:
        raise MarcParseError("Leader positions 12-16 must contain numeric base address") from exc

    directory = text[24 : base_address - 1]
    if len(directory) % 12 != 0:
        raise MarcParseError("MARC directory length must be divisible by 12")

    fields = []
    data = text[base_address:]
    for offset in range(0, len(directory), 12):
        entry = directory[offset : offset + 12]
        tag = entry[0:3]
        try:
            length = int(entry[3:7])
            start = int(entry[7:12])
        except ValueError as exc:
            raise MarcParseError(f"Directory entry for {tag} has non-numeric length/start") from exc

        field_data = data[start : start + length - 1]
        if tag.startswith("00"):
            fields.append({"tag": tag, "value": field_data})
            continue

        if len(field_data) < 2:
            raise MarcParseError(f"Data field {tag} is too short for indicators")
        indicators = [field_data[0], field_data[1]]
        subfields = []
        for chunk in field_data[2:].split(SUBFIELD_DELIMITER):
            if not chunk:
                continue
            subfields.append({"code": chunk[0], "value": chunk[1:]})
        fields.append({"tag": tag, "indicators": indicators, "subfields": subfields})

    return {"leader": leader, "fields": fields}


def field_values(parsed: dict, tag: str, code: str | None = None) -> list[str]:
    values: list[str] = []
    for field in parsed.get("fields", []):
        if field.get("tag") != tag:
            continue
        if code is None and "value" in field:
            values.append(field["value"])
        elif code is not None:
            values.extend(
                subfield["value"]
                for subfield in field.get("subfields", [])
                if subfield.get("code") == code
            )
    return values


def first_field_value(parsed: dict, tag: str, code: str | None = None) -> str:
    values = field_values(parsed, tag, code)
    return values[0] if values else ""


def validate_parsed_record(parsed: dict) -> list[str]:
    errors: list[str] = []
    leader = parsed.get("leader", "")
    if len(leader) != 24:
        errors.append("Leader must be exactly 24 characters")
    for field in parsed.get("fields", []):
        tag = field.get("tag", "")
        if len(tag) != 3 or not tag.isdigit():
            errors.append(f"Invalid tag: {tag}")
        if tag.startswith("00") and "value" not in field:
            errors.append(f"Control field {tag} must contain value")
        if not tag.startswith("00") and len(field.get("indicators", [])) != 2:
            errors.append(f"Data field {tag} must contain two indicators")
    return errors

