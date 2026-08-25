# G2-B Structured Baseline

This package implements the deterministic boundary between G2-A typed rules,
PostgreSQL staging, and the allowlisted Structured Tool.

## What it does

- validates the exact G1 and G2-A report sets and their `PASS` status;
- rebuilds all four typed staging tables and all 280 source-column contracts;
- verifies the Priority A semantic mapping against official schema descriptions;
- iterates every official data row without modifying the workbooks;
- validates row counts, `source_row_id` uniqueness, parse states, and source
  size/mtime/SHA-256 immutability;
- compiles EQ, range, multi-filter, ASC/DESC sort, Top-N, and COUNT query shapes;
- optionally loads and validates PostgreSQL in one transaction; and
- writes exactly four aggregate-only reports outside the repository.

The database may contain all 280 typed fields, but only Priority A fields with
`CONFIRMED` semantic status are exposed through the trusted query registry.
Identifiers are selected from that registry and values are bound parameters.
Free-form SQL and NL2SQL are not accepted.

## Offline preflight

From `backend/`:

```powershell
python -m pipeline.structured `
  --raw-dir ..\data\raw `
  --schema-dir ..\data\schema `
  --g1-report-dir ..\outputs\reports\g1 `
  --g2a-report-dir ..\outputs\reports\g2a `
  --output-dir ..\outputs\reports\g2b
```

Offline validation produces `PARTIAL`, because a live PostgreSQL load was not
performed. This is intentional and is reported as `database.status=NOT_RUN`.
Even a successful load remains `PARTIAL` until all required Core QA query
shapes are executed against PostgreSQL and their result shapes are validated;
compile-only checks never promote the gate to `PASS`.

## Explicit PostgreSQL load

Set `DATABASE_URL` in the process environment and add `--execute-db`:

```powershell
$env:DATABASE_URL = '<configured outside source control>'
python -m pipeline.structured `
  --raw-dir ..\data\raw `
  --schema-dir ..\data\schema `
  --g1-report-dir ..\outputs\reports\g1 `
  --g2a-report-dir ..\outputs\reports\g2a `
  --output-dir ..\outputs\reports\g2b `
  --execute-db
```

There is deliberately no command-line URL argument. The URL and connection
errors are not copied into stdout or reports. If `--execute-db` is present but
`DATABASE_URL` is absent or authentication cannot be established, the result
remains honest `PARTIAL`/`NOT_RUN` or `PARTIAL`/`BLOCKED` rather than claiming a
load.

## Output contract

The output directory must be outside this repository and must contain no
unexpected entries. The runner atomically writes exactly:

- `g2b_core_field_mapping.json`
- `g2b_structured_schema.json`
- `g2b_validation_summary.json`
- `g2b_summary.md`

No source rows, raw values, normalized row values, query values, credentials,
or connection strings are copied into these reports.

## Deliberate exclusions

G2-B does not implement vector or graph retrieval, ontology TTL, embeddings,
reranking, HCX, tax/cost logic, external APIs, or full 280-field semantic
approval. COUNT is deterministic but does not fabricate row-level evidence;
aggregate evidence policy remains a Gold Set follow-up.
