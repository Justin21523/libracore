from __future__ import annotations

import csv
import io
from xml.etree import ElementTree as ET

from django.utils import timezone

from apps.acquisitions.models import AcquisitionOrderLine
from apps.catalog.models import BibliographicRecord
from apps.circulation.models import FineFee, Patron
from apps.holdings.models import Holding, Item
from apps.marc.models import MarcRecord
from apps.repository.models import DigitalObject

MARC_NS = "http://www.loc.gov/MARC21/slim"
OAI_DC_NS = "http://www.openarchives.org/OAI/2.0/oai_dc/"
DC_NS = "http://purl.org/dc/elements/1.1/"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

ET.register_namespace("marc", MARC_NS)
ET.register_namespace("oai_dc", OAI_DC_NS)
ET.register_namespace("dc", DC_NS)
ET.register_namespace("xsi", XSI_NS)


def marcxml_for_bib(bib: BibliographicRecord) -> str:
    marc = (
        MarcRecord.objects.filter(
            bibliographic_record=bib, format_type=MarcRecord.FormatType.BIBLIOGRAPHIC
        )
        .exclude(marcxml="")
        .first()
    )
    if marc:
        return marc.marcxml
    marc = (
        MarcRecord.objects.filter(
            bibliographic_record=bib, format_type=MarcRecord.FormatType.BIBLIOGRAPHIC
        )
        .exclude(parsed_json={})
        .first()
    )
    if marc:
        return marcxml_from_parsed(marc.parsed_json)
    return marcxml_from_bib(bib)


def marcxml_collection(bibs) -> tuple[str, int]:
    collection = ET.Element(f"{{{MARC_NS}}}collection")
    count = 0
    for bib in bibs:
        try:
            record = ET.fromstring(marcxml_for_bib(bib))
        except ET.ParseError:
            record = ET.fromstring(marcxml_from_bib(bib))
        collection.append(record)
        count += 1
    return _xml_bytes(collection).decode("utf-8"), count


def marcxml_from_parsed(parsed: dict) -> str:
    record = ET.Element(f"{{{MARC_NS}}}record")
    leader = ET.SubElement(record, f"{{{MARC_NS}}}leader")
    leader.text = parsed.get("leader", " " * 24)
    for field in parsed.get("fields", []):
        tag = field.get("tag", "")
        if "value" in field:
            control = ET.SubElement(record, f"{{{MARC_NS}}}controlfield", {"tag": tag})
            control.text = field.get("value", "")
            continue
        data = ET.SubElement(
            record,
            f"{{{MARC_NS}}}datafield",
            {
                "tag": tag,
                "ind1": (field.get("indicators") or [" ", " "])[0] or " ",
                "ind2": (field.get("indicators") or [" ", " "])[1] or " ",
            },
        )
        for subfield in field.get("subfields", []):
            node = ET.SubElement(data, f"{{{MARC_NS}}}subfield", {"code": subfield.get("code", "")})
            node.text = subfield.get("value", "")
    return _xml_bytes(record).decode("utf-8")


def marcxml_from_bib(bib: BibliographicRecord) -> str:
    instance = bib.instance
    record = ET.Element(f"{{{MARC_NS}}}record")
    ET.SubElement(record, f"{{{MARC_NS}}}leader").text = "00000nam a2200000 a 4500"
    ET.SubElement(record, f"{{{MARC_NS}}}controlfield", {"tag": "001"}).text = (
        bib.control_number or str(bib.id)
    )
    if bib.source:
        ET.SubElement(record, f"{{{MARC_NS}}}controlfield", {"tag": "003"}).text = bib.source
    if instance:
        title = ET.SubElement(
            record, f"{{{MARC_NS}}}datafield", {"tag": "245", "ind1": "0", "ind2": "0"}
        )
        ET.SubElement(
            title, f"{{{MARC_NS}}}subfield", {"code": "a"}
        ).text = instance.title_statement
        if instance.responsibility_statement:
            ET.SubElement(
                title, f"{{{MARC_NS}}}subfield", {"code": "c"}
            ).text = instance.responsibility_statement
        if instance.publisher or instance.publication_date:
            pub = ET.SubElement(
                record, f"{{{MARC_NS}}}datafield", {"tag": "264", "ind1": " ", "ind2": "1"}
            )
            ET.SubElement(pub, f"{{{MARC_NS}}}subfield", {"code": "b"}).text = instance.publisher
            ET.SubElement(
                pub, f"{{{MARC_NS}}}subfield", {"code": "c"}
            ).text = instance.publication_date
    return _xml_bytes(record).decode("utf-8")


def oai_dc_for_bib(bib: BibliographicRecord) -> ET.Element:
    dc = _dc_root()
    instance = bib.instance
    work = bib.work
    if instance:
        _dc(dc, "title", instance.title_statement)
        _dc(dc, "publisher", instance.publisher)
        _dc(dc, "date", instance.publication_date)
        _dc(dc, "type", instance.resource_type)
        for identifier in instance.identifiers:
            if isinstance(identifier, dict):
                _dc(dc, "identifier", identifier.get("value", ""))
        for note in instance.notes:
            if isinstance(note, dict):
                _dc(dc, "description", note.get("value", ""))
    if work:
        _dc(dc, "language", work.language_hint)
        _dc(dc, "description", work.summary)
        for subject in work.subjects.all():
            _dc(dc, "subject", subject.label)
    for subject in bib.metadata.get("subjects", []):
        if isinstance(subject, dict):
            _dc(dc, "subject", subject.get("label", ""))
    _dc(dc, "identifier", bib.control_number or str(bib.id))
    return dc


def oai_dc_for_digital_object(obj: DigitalObject) -> ET.Element:
    dc = _dc_root()
    metadata = obj.dc_metadata or {}
    _dc(dc, "title", metadata.get("title") or obj.title)
    for key in [
        "creator",
        "subject",
        "description",
        "publisher",
        "contributor",
        "date",
        "type",
        "format",
        "identifier",
        "source",
        "language",
        "relation",
        "coverage",
        "rights",
    ]:
        value = metadata.get(key)
        values = value if isinstance(value, list) else [value]
        for item in values:
            _dc(dc, key, item)
    if obj.rights_statement:
        _dc(dc, "rights", obj.rights_statement)
    _dc(dc, "identifier", f"/repository/{obj.id}/")
    for asset in obj.file_assets.filter(access_level="public"):
        _dc(dc, "identifier", f"/repository/files/{asset.id}/download/")
    return dc


def oai_dc_string(element: ET.Element) -> str:
    return _xml_bytes(element).decode("utf-8")


def csv_export(export_type: str) -> tuple[str, int]:
    output = io.StringIO()
    writer = csv.writer(output)
    count = 0
    if export_type == "csv_patrons":
        writer.writerow(
            ["barcode", "username", "email", "patron_type", "expiry_date", "home_branch"]
        )
        for patron in Patron.objects.select_related("user", "home_branch").all():
            writer.writerow(
                [
                    patron.barcode,
                    patron.user.username,
                    patron.user.email,
                    patron.patron_type,
                    patron.expiry_date or "",
                    patron.home_branch.name if patron.home_branch else "",
                ]
            )
            count += 1
    elif export_type == "csv_items":
        writer.writerow(["barcode", "status", "title", "branch", "location", "due_back_at"])
        for item in Item.objects.select_related(
            "holding__instance", "holding__branch", "holding__location"
        ).all():
            writer.writerow(
                [
                    item.barcode,
                    item.status,
                    item.holding.instance.title_statement,
                    item.holding.branch.name,
                    item.holding.location.name,
                    item.due_back_at or "",
                ]
            )
            count += 1
    elif export_type == "csv_holdings":
        writer.writerow(["title", "branch", "location", "textual_holdings", "public_note"])
        for holding in Holding.objects.select_related("instance", "branch", "location").all():
            writer.writerow(
                [
                    holding.instance.title_statement,
                    holding.branch.name,
                    holding.location.name,
                    holding.textual_holdings,
                    holding.public_note,
                ]
            )
            count += 1
    elif export_type == "csv_acquisitions":
        writer.writerow(
            [
                "order",
                "title",
                "quantity",
                "received_quantity",
                "cancelled_quantity",
                "receiving_status",
            ]
        )
        for line in AcquisitionOrderLine.objects.select_related("order").all():
            writer.writerow(
                [
                    line.order.order_number,
                    line.title,
                    line.quantity,
                    line.received_quantity,
                    line.cancelled_quantity,
                    line.receiving_status,
                ]
            )
            count += 1
    elif export_type == "csv_fees":
        writer.writerow(["patron", "reason", "fee_type", "status", "amount", "balance_amount"])
        for fee in FineFee.objects.select_related("patron").all():
            writer.writerow(
                [
                    fee.patron.barcode,
                    fee.reason,
                    fee.fee_type,
                    fee.status,
                    fee.amount,
                    fee.balance_amount,
                ]
            )
            count += 1
    else:
        raise ValueError(f"Unsupported CSV export type: {export_type}")
    return output.getvalue(), count


def approved_bibliographic_records():
    return BibliographicRecord.objects.filter(
        status=BibliographicRecord.Status.APPROVED
    ).select_related("work", "instance")


def published_digital_objects():
    return (
        DigitalObject.objects.filter(status=DigitalObject.Status.PUBLISHED)
        .select_related("bibliographic_record")
        .prefetch_related("file_assets")
    )


def _dc_root() -> ET.Element:
    return ET.Element(
        f"{{{OAI_DC_NS}}}dc",
        {
            f"{{{XSI_NS}}}schemaLocation": (
                "http://www.openarchives.org/OAI/2.0/oai_dc/ "
                "http://www.openarchives.org/OAI/2.0/oai_dc.xsd"
            )
        },
    )


def _dc(root: ET.Element, name: str, value) -> None:
    if value in [None, ""]:
        return
    node = ET.SubElement(root, f"{{{DC_NS}}}{name}")
    node.text = str(value)


def _xml_bytes(element: ET.Element) -> bytes:
    return ET.tostring(element, encoding="utf-8", xml_declaration=True)


def datestamp(value) -> str:
    return timezone.localtime(value).date().isoformat()
