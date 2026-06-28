# LibraCore Architecture Notes

## Domain Rule

Do not collapse bibliographic, holdings, item, and circulation data into a single book table.

The core descriptive stack is:

```text
Work -> Expression -> Instance/Manifestation -> Holding -> Item
```

MARC21 is stored as source/exchange metadata in `MarcRecord`. Application workflows operate on normalized domain entities while retaining the original MARC record for audit, re-export, and remapping.

## MARC21 Mapping Policy

- Preserve raw ISO2709 bytes and parsed JSON.
- Normalize identifiers, title statement, publication statement, physical description, notes, subjects, contributors, and classifications into domain fields.
- Keep unsupported or ambiguous MARC fields in `BibliographicRecord.metadata` until a deliberate mapping is added.
- Treat MARC Bibliographic, Authority, and Holdings as distinct record types.

## Cataloging Workbench Phase B

MARC import is review-first:

```text
MarcImportBatch -> MarcImportRecord -> parse/map/validate -> approve -> BibliographicRecord + MarcRecord
```

Supported input formats:

- ISO2709, including multi-record files split by record terminator.
- MARCXML using MARC21 slim `record`, `leader`, `controlfield`, `datafield`, and `subfield`.
- JSON MARC using the canonical parsed schema `{leader, fields}`.

Staff UI entry points:

- `/staff/cataloging/imports/`
- `/staff/cataloging/imports/new/`
- `/staff/cataloging/imports/<batch_id>/`
- `/staff/cataloging/import-records/<record_id>/review/`

Import rules:

- Parsing does not create official catalog records.
- Approval creates `Work`, `Instance`, `BibliographicRecord`, and `MarcRecord`.
- Invalid, rejected, approved, and conflict records cannot be approved again.
- Existing `source + control_number` or matching identifier marks an import record as `conflict`; Phase B does not overwrite existing catalog records.
- Authority suggestions are advisory. They do not create links unless a cataloger accepts a matched authority or explicitly creates a provisional authority.

## API Shape

All MVP resources are exposed as DRF viewsets under `/api/`. The endpoints are intentionally close to entity names so coding agents can build workflows without inventing hidden service boundaries.

Key endpoints:

- `/api/works/`
- `/api/instances/`
- `/api/bibliographic-records/`
- `/api/marc-records/`
- `/api/marc-records/parse/`
- `/api/authorities/`
- `/api/vocabulary-terms/`
- `/api/holdings/`
- `/api/items/`
- `/api/patrons/`
- `/api/loans/`
- `/api/search-documents/`
- `/api/search-documents/search/`
- `/api/search-documents/facets/`
- `/api/search-documents/rebuild/`

## Discovery Phase C

Public OPAC entry points:

- `/`
- `/search/`
- `/records/<instance_id>/`
- `/records/<instance_id>/availability/`

Discovery indexing is explicit:

```text
approved BibliographicRecord + Instance + Holdings + Items -> SearchDocument
```

Rules:

- Only approved bibliographic records are indexed.
- Availability is derived from public holdings/items and never exposes patron identity.
- PostgreSQL uses runtime `SearchVector`/`SearchQuery`; SQLite uses normalized text and CJK token fallback.
- OpenCC and jieba generate simplified/traditional variants and CJK tokens during indexing.
- Rebuild with `python3 manage.py rebuild_discovery_index` or staff-only `POST /api/search-documents/rebuild/`.
- Automatic signal-based indexing is intentionally deferred.

## Authority Control Phase D

Authority control is handled as a governed workflow, not just labels on bibliographic records.

Staff entry points:

- `/staff/authorities/`
- `/staff/authorities/new/`
- `/staff/authorities/<authority_id>/`

Public browse entry points:

- `/authorities/`
- `/authorities/<authority_id>/`
- `/subjects/`

Rules:

- Each authority should have one preferred authorized access point.
- Variant access points are searchable but cannot be preferred.
- Merging transfers Work/Instance/MARC/suggestion links to the target authority, copies source headings as target variants, and marks the source authority deprecated.
- Deprecated authorities are retained and may point to a replacement authority.
- External identifiers validate known URI shapes for id.loc.gov, VIAF, ORCID, and FAST, but Phase D does not call external APIs.
- Discovery indexing includes authority variant labels, so variant searches can retrieve records linked to preferred headings.
- Authority changes require explicit `rebuild_discovery_index` until automatic indexing is added.

## Next Safe Implementation Tasks

1. Add staff-facing templates for authority lookup, circulation desk, and OPAC.
2. Add notice generation for hold-ready, overdue, and payment receipt workflows.
3. Add automatic or async search reindexing after cataloging, authority, and circulation changes.
4. Add MARC Authority and Holdings mapping modules using the same parser contract.
5. Add duplicate-resolution and catalog merge workflows for MARC import conflicts.

## Circulation Phase A

Circulation mutations should go through `apps.circulation.services`, not direct model writes.

Implemented service entry points:

- `checkout_item`
- `return_item`
- `renew_loan`
- `place_hold`
- `cancel_hold`
- `expire_ready_holds`
- `assess_overdue_fee`
- `record_payment`
- `waive_fee`

The policy resolver uses `patron_type`, branch, location, and `Instance.resource_type`, then falls back to the default policy seeded by `seed_libracore`.
