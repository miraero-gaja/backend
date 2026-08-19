# Deterministic typed staging

`pipeline.normalize` defines the G2-A conversion contract. It is a pure-Python
library: it does not write a workbook, create a database table, or connect to
PostgreSQL, Graph, Vector, HCX, or any other external system.

## Guarantees

- Every `ParseResult` retains the exact `raw_value`.
- Missing, empty-string, whitespace-only, parse-error, and unsupported cases
  stay distinguishable through `ParseStatus`.
- Text declared by the schema stays `TEXT`, even when its values look numeric.
- Schema `numeric`, `decimal`, and `double precision` values use `Decimal`.
- Schema `bigint` values use Python integers. Boolean and fractional values are
  rejected rather than silently coerced.
- Schema timestamps and dates use strict ISO-shaped parsers. Supported timestamp
  strings are `YYYY-MM-DD HH:MM:SS` or the equivalent `T` separator, with an
  optional 1-6 digit fraction. Time-zone presence must agree with the declared
  timestamp type. Dates use exactly `YYYY-MM-DD`.
- Numeric separators, percent signs, whitespace trimming, unit conversion, null
  imputation, and unsupported declared types are never converted implicitly.
- `PARSE_ERROR` retains the raw value and has no normalized value. An unsupported
  rule produces `NOT_APPLICABLE`; it cannot fall through to text conversion.

The six parse states are:

```text
OK
MISSING
EMPTY
WHITESPACE_ONLY
PARSE_ERROR
NOT_APPLICABLE
```

Use `build_typed_rule(...)` to derive the target and transform from the schema
declaration, then call `normalize_value(raw_value, rule)`. `TypedRule.to_dict()`
is safe for aggregate rule reports. `ParseResult.to_dict()` intentionally
contains its per-row raw value and must not be copied into G2-A aggregate report
artifacts.

## Source lineage

`derive_source_row_id(...)` uses these inputs only:

```text
source_table
source_file_sha256
source_sheet
source_excel_row
```

The ID is not a business primary key. Version `v1` hashes a domain/version tag
plus each UTF-8 input encoded with an unsigned 8-byte length prefix; the Excel
row uses canonical base-10 text. The result is
`srid:v1:<sha256>`. This avoids delimiter ambiguity and reproduces the same ID
for the same workbook snapshot and row position.

## Whitespace review

`analyze_trim_impact(...)` evaluates a hypothetical Python `str.strip()` without
changing values. It reports distinct counts before and after, collapsed distinct
count, collision groups, `CONFLICT` status, and optional identifier-uniqueness
change. Its result contains counts only: no raw values or digests leave the
analysis function. A `CONFLICT` is evidence against automatic trimming, not an
instruction to mutate the source.

Identifier uniqueness requires all rows to be nonblank and distinct. Missing,
exact-empty, and whitespace-only counts stay explicit so a nullable declared
key cannot be presented as an enforceable business primary key.

## Official G2-A run

From the backend repository, run:

```powershell
python -m pipeline.normalize `
  --raw-dir ..\data\raw `
  --schema-dir ..\data\schema `
  --g1-report-dir ..\outputs\reports\g1 `
  --output-dir ..\outputs\reports\g2a
```

The runner rechecks the actual schema workbooks against the G1 schema profile,
validates the G1 manifest and schema diff, fingerprints all G1 inputs, and
rechecks all eight source workbooks after the aggregate-only scan. It atomically
writes exactly:

- `g2a_typed_rules.json`
- `g2a_coverage_matrix.json`
- `g2a_lineage_summary.json`
- `g2a_mapping_review.json`
- `g2a_summary.md`

The output directory is rejected if it overlaps a source or G1-report
directory. Existing unexpected output entries are never deleted or overwritten.
