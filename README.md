# LibraCore

LibraCore is a Django-based library information system scaffold designed around library and information science concepts rather than a single `Book` table.

Implemented baseline:

- Work / Expression / Instance / BibliographicRecord catalog model.
- MARC21 raw record storage, ISO2709 parser, validator, and bibliographic mapping service.
- MARC import batches for ISO2709, MARCXML, and JSON MARC with review-first approval workflow.
- Staff cataloging workbench for upload, parsing, mapping preview, approval/rejection, and authority suggestions.
- Discovery indexing and public OPAC with PostgreSQL FTS strategy, SQLite fallback, OpenCC/jieba CJK normalization, facets, and availability display.
- Authority control models with authorized and variant access-point proxy concepts.
- Authority control workbench with preferred/variant access points, relations, deprecation, merge, URI validation, and public authority/subject browse.
- Controlled vocabulary, classification, and call-number models.
- Branch, location, holding, item, patron, loan, hold request, acquisitions, serials, ERM, repository, discovery, analytics, and audit models.
- Circulation policy engine, staff checkout/return/renew workflows, hold queues, overdue fees, payment allocation, fee waivers, and circulation audit logging.
- DRF endpoints under `/api/` and Django admin registration.
- Tests for MARC parsing/mapping/import, cataloging workbench, discovery/OPAC, Work/Instance/Item/Loan separation, and circulation workflows.
- Authority service/API/view tests for merge, deprecation, browse, and Discovery variant-label indexing.

## Local Setup

```bash
python3 -m pip install -r requirements.txt
python3 manage.py migrate
python3 manage.py seed_libracore
python3 manage.py runserver
```

Default development database is SQLite. For PostgreSQL, set `DATABASE_URL` to a value beginning with `postgres` and provide `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, and `POSTGRES_PORT`.

## Verification

```bash
python3 manage.py check
python3 manage.py makemigrations --check --dry-run
pytest -q
```

## Current Boundaries

This is the executable MVP architecture, not the full production system. The next implementation steps are:

- Add explicit RBAC permission policies per endpoint and staff workflow.
- Add automatic discovery reindex hooks or async indexing queue.
- Add OpenSearch/Elasticsearch as the production-scale discovery backend.
- Add MARC Authority and Holdings mapping services.
- Add duplicate bibliographic conflict resolution and merge/update workflows.
- Add notice generation and reader-facing account pages for existing circulation workflows.
- Add OAI-PMH provider and Dublin Core export for repository records.
- Add external authority lookup adapters for id.loc.gov, VIAF, and ORCID.
