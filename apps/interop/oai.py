from __future__ import annotations

from xml.etree import ElementTree as ET

from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import BibliographicRecord
from apps.repository.models import DigitalObject

from .metadata import (
    datestamp,
    marcxml_for_bib,
    oai_dc_for_bib,
    oai_dc_for_digital_object,
    published_digital_objects,
)
from .services import bib_by_oai_identifier

OAI_NS = "http://www.openarchives.org/OAI/2.0/"
ET.register_namespace("", OAI_NS)


def oai_response(request) -> bytes:
    verb = request.GET.get("verb", "")
    root = ET.Element(f"{{{OAI_NS}}}OAI-PMH")
    ET.SubElement(root, f"{{{OAI_NS}}}responseDate").text = timezone.now().isoformat()
    ET.SubElement(root, f"{{{OAI_NS}}}request", {"verb": verb}).text = request.build_absolute_uri(
        reverse("interop:oai")
    )
    if verb == "Identify":
        _identify(root, request)
    elif verb == "ListMetadataFormats":
        _metadata_formats(root)
    elif verb == "ListSets":
        _sets(root)
    elif verb == "ListIdentifiers":
        _list_records(root, request, identifiers_only=True)
    elif verb == "ListRecords":
        _list_records(root, request, identifiers_only=False)
    elif verb == "GetRecord":
        _get_record(root, request)
    else:
        _error(root, "badVerb", "Unsupported or missing OAI-PMH verb.")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _identify(root, request):
    identify = ET.SubElement(root, f"{{{OAI_NS}}}Identify")
    ET.SubElement(identify, f"{{{OAI_NS}}}repositoryName").text = "LibraCore"
    ET.SubElement(identify, f"{{{OAI_NS}}}baseURL").text = request.build_absolute_uri(
        reverse("interop:oai")
    )
    ET.SubElement(identify, f"{{{OAI_NS}}}protocolVersion").text = "2.0"
    ET.SubElement(identify, f"{{{OAI_NS}}}adminEmail").text = "admin@libracore.local"
    ET.SubElement(identify, f"{{{OAI_NS}}}earliestDatestamp").text = "1970-01-01"
    ET.SubElement(identify, f"{{{OAI_NS}}}deletedRecord").text = "no"
    ET.SubElement(identify, f"{{{OAI_NS}}}granularity").text = "YYYY-MM-DD"


def _metadata_formats(root):
    parent = ET.SubElement(root, f"{{{OAI_NS}}}ListMetadataFormats")
    for prefix, schema, namespace in [
        (
            "oai_dc",
            "http://www.openarchives.org/OAI/2.0/oai_dc.xsd",
            "http://www.openarchives.org/OAI/2.0/oai_dc/",
        ),
        (
            "marcxml",
            "http://www.loc.gov/standards/marcxml/schema/MARC21slim.xsd",
            "http://www.loc.gov/MARC21/slim",
        ),
    ]:
        fmt = ET.SubElement(parent, f"{{{OAI_NS}}}metadataFormat")
        ET.SubElement(fmt, f"{{{OAI_NS}}}metadataPrefix").text = prefix
        ET.SubElement(fmt, f"{{{OAI_NS}}}schema").text = schema
        ET.SubElement(fmt, f"{{{OAI_NS}}}metadataNamespace").text = namespace


def _sets(root):
    parent = ET.SubElement(root, f"{{{OAI_NS}}}ListSets")
    for spec, name in [
        ("bibliographic", "Bibliographic records"),
        ("repository", "Digital repository"),
    ]:
        item = ET.SubElement(parent, f"{{{OAI_NS}}}set")
        ET.SubElement(item, f"{{{OAI_NS}}}setSpec").text = spec
        ET.SubElement(item, f"{{{OAI_NS}}}setName").text = name


def _list_records(root, request, *, identifiers_only: bool):
    metadata_prefix = request.GET.get("metadataPrefix", "oai_dc")
    if metadata_prefix not in ["oai_dc", "marcxml"]:
        _error(root, "cannotDisseminateFormat", "Unsupported metadataPrefix.")
        return
    parent = ET.SubElement(
        root, f"{{{OAI_NS}}}{'ListIdentifiers' if identifiers_only else 'ListRecords'}"
    )
    for source, obj in _iter_sources(request):
        if metadata_prefix == "marcxml" and source != "bibliographic":
            continue
        _record(parent, source, obj, metadata_prefix, identifiers_only=identifiers_only)


def _get_record(root, request):
    identifier = request.GET.get("identifier", "")
    metadata_prefix = request.GET.get("metadataPrefix", "oai_dc")
    source, obj = _resolve_identifier(identifier)
    if not obj:
        _error(root, "idDoesNotExist", "Identifier does not exist.")
        return
    if metadata_prefix == "marcxml" and source != "bibliographic":
        _error(
            root, "cannotDisseminateFormat", "MARCXML is only available for bibliographic records."
        )
        return
    parent = ET.SubElement(root, f"{{{OAI_NS}}}GetRecord")
    _record(parent, source, obj, metadata_prefix, identifiers_only=False)


def _iter_sources(request):
    set_spec = request.GET.get("set")
    if set_spec in [None, "", "bibliographic"]:
        for bib in BibliographicRecord.objects.filter(
            status=BibliographicRecord.Status.APPROVED
        ).select_related("work", "instance"):
            if _date_filter(request, bib.updated_at):
                yield "bibliographic", bib
    if set_spec in [None, "", "repository"]:
        for obj in published_digital_objects():
            if _date_filter(request, obj.updated_at):
                yield "repository", obj


def _record(parent, source: str, obj, metadata_prefix: str, *, identifiers_only: bool):
    record = parent if identifiers_only else ET.SubElement(parent, f"{{{OAI_NS}}}record")
    header = ET.SubElement(record, f"{{{OAI_NS}}}header")
    ET.SubElement(header, f"{{{OAI_NS}}}identifier").text = _identifier(source, obj)
    ET.SubElement(header, f"{{{OAI_NS}}}datestamp").text = datestamp(obj.updated_at)
    ET.SubElement(header, f"{{{OAI_NS}}}setSpec").text = source
    if identifiers_only:
        return
    metadata = ET.SubElement(record, f"{{{OAI_NS}}}metadata")
    if metadata_prefix == "marcxml":
        metadata.append(ET.fromstring(marcxml_for_bib(obj)))
    elif source == "bibliographic":
        metadata.append(oai_dc_for_bib(obj))
    else:
        metadata.append(oai_dc_for_digital_object(obj))


def _resolve_identifier(identifier: str):
    bib = bib_by_oai_identifier(identifier)
    if bib:
        return "bibliographic", bib
    obj = DigitalObject.objects.filter(oai_identifier=identifier).first()
    if obj:
        return "repository", obj
    return None, None


def _identifier(source: str, obj) -> str:
    if source == "repository":
        return obj.oai_identifier or f"oai:libracore:repository:{obj.id}"
    return f"oai:libracore:bib:{obj.id}"


def _date_filter(request, value) -> bool:
    current = datestamp(value)
    from_date = request.GET.get("from")
    until = request.GET.get("until")
    if from_date and current < from_date:
        return False
    if until and current > until:
        return False
    return True


def _error(root, code: str, message: str):
    ET.SubElement(root, f"{{{OAI_NS}}}error", {"code": code}).text = message
