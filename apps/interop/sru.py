from __future__ import annotations

import re

from apps.discovery.search import search_documents

from .metadata import oai_dc_for_bib, oai_dc_string

SUPPORTED_FIELDS = {"title", "creator", "subject", "isbn", "issn", "keyword"}


def sru_search_response(
    query: str, *, start_record: int = 1, maximum_records: int = 10, record_schema: str = "json"
) -> dict:
    search_query = cql_lite_to_query(query)
    page = max((start_record - 1) // maximum_records + 1, 1)
    result_page = search_documents(query=search_query, page=page, per_page=maximum_records)
    records = []
    for position, document in enumerate(result_page.page_obj.object_list, start=start_record):
        if record_schema == "dc":
            bib = document.instance.bib_records.filter(status="approved").first()
            data = oai_dc_string(oai_dc_for_bib(bib)) if bib else ""
        else:
            data = {
                "title": document.title_main,
                "creator": document.creator,
                "subject": document.subject,
                "identifiers": document.identifiers,
                "publisher": document.publisher,
                "publication_date": document.publication_date,
                "instance_id": str(document.instance_id),
            }
        records.append({"position": position, "schema": record_schema, "recordData": data})
    return {
        "version": "1.2-lite",
        "numberOfRecords": result_page.total,
        "records": records,
        "facets": result_page.facets,
    }


def cql_lite_to_query(query: str) -> str:
    query = (query or "").strip()
    if not query:
        return ""
    match = re.match(r"(?P<field>\w+)\s*=\s*\"(?P<value>.+)\"", query)
    if not match:
        return query
    field = match.group("field")
    value = match.group("value")
    if field not in SUPPORTED_FIELDS:
        return value
    return value
