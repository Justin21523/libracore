from __future__ import annotations

import json
import xml.etree.ElementTree as ET

from apps.marc.models import MarcImportBatch
from apps.marc.parser import RECORD_TERMINATOR, MarcParseError, parse_iso2709, validate_parsed_record


class MarcImportError(ValueError):
    pass


def parse_records(payload: bytes | str, import_format: str) -> list[dict]:
    if import_format == MarcImportBatch.ImportFormat.ISO2709:
        return parse_iso2709_records(payload)
    if import_format == MarcImportBatch.ImportFormat.MARCXML:
        return parse_marcxml_records(payload)
    if import_format == MarcImportBatch.ImportFormat.JSON:
        return parse_json_marc_records(payload)
    raise MarcImportError(f"Unsupported MARC import format: {import_format}")


def parse_iso2709_records(payload: bytes | str) -> list[dict]:
    text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
    raw_records = [record + RECORD_TERMINATOR for record in text.split(RECORD_TERMINATOR) if record]
    records = []
    for raw_record in raw_records:
        records.append({"raw": raw_record, "parsed": parse_iso2709(raw_record)})
    return records


def parse_marcxml_records(payload: bytes | str) -> list[dict]:
    text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
    root = ET.fromstring(text)
    records = []
    if _local_name(root.tag) == "record":
        record_nodes = [root]
    else:
        record_nodes = [node for node in root.iter() if _local_name(node.tag) == "record"]
    for node in record_nodes:
        parsed = _parse_marcxml_record(node)
        records.append({"raw": ET.tostring(node, encoding="unicode"), "parsed": parsed})
    return records


def parse_json_marc_records(payload: bytes | str) -> list[dict]:
    text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
    loaded = json.loads(text)
    items = loaded if isinstance(loaded, list) else loaded.get("records", [loaded])
    records = []
    for item in items:
        if not isinstance(item, dict) or "leader" not in item or "fields" not in item:
            raise MarcParseError("JSON MARC record must contain leader and fields")
        errors = validate_parsed_record(item)
        if errors:
            raise MarcParseError("; ".join(errors))
        records.append({"raw": json.dumps(item, ensure_ascii=False), "parsed": item})
    return records


def _parse_marcxml_record(node: ET.Element) -> dict:
    leader = ""
    fields = []
    for child in node:
        name = _local_name(child.tag)
        if name == "leader":
            leader = child.text or ""
        elif name == "controlfield":
            fields.append({"tag": child.attrib["tag"], "value": child.text or ""})
        elif name == "datafield":
            fields.append(
                {
                    "tag": child.attrib["tag"],
                    "indicators": [child.attrib.get("ind1", " "), child.attrib.get("ind2", " ")],
                    "subfields": [
                        {"code": sub.attrib["code"], "value": sub.text or ""}
                        for sub in child
                        if _local_name(sub.tag) == "subfield"
                    ],
                }
            )
    parsed = {"leader": leader, "fields": fields}
    errors = validate_parsed_record(parsed)
    if errors:
        raise MarcParseError("; ".join(errors))
    return parsed


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]

