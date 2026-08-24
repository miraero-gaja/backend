# G1 Data Profiling

This package inventories and profiles the four official schema/datarows pairs
without modifying or copying source workbooks. It is an offline pipeline and is
not imported by the FastAPI request path.

## Install

Install the optional data dependency separately from API runtime packages:

```powershell
python -m pip install -e ".[data,test]"
```

`openpyxl` is the only data dependency. It is used in read-only streaming mode
because the source format is XLSX and the largest workbook cannot safely be
loaded as an in-memory worksheet. XLSX package metadata such as formula cells,
merged cells, declared dimensions, and physical row elements is read with the
Python standard library.

## Run

From the backend repository:

```powershell
python -m pipeline.profiling `
  --raw-dir ..\data\raw `
  --schema-dir ..\data\schema `
  --output-dir ..\outputs\reports\g1
```

The output directory is mandatory and is rejected if it is inside either
source directory. A successful run atomically writes exactly:

- `g1_file_manifest.json`
- `g1_schema_profile.json`
- `g1_data_profile.json`
- `g1_schema_diff.json`
- `g1_summary.md`

The profiler fingerprints all eight files before processing and rechecks size,
nanosecond timestamp, and SHA-256 before writing reports. Distinct counts use
typed SHA-256 digests in a deleted-on-exit SQLite temporary database, so source
rows and arbitrary value samples are not copied to generated reports or
retained as a staging dataset. Reports include only requested bounded evidence,
such as numeric/date extrema, finite numeric-like-string extrema, observed
boolean-code representations, and complete value counts for low-cardinality
code candidates (at most 100 distinct source tokens). Code meanings are never
inferred from those counts.

## Interpretation limits

- The official logical IDs and expected row counts are configuration, not
  inferred facts.
- `PRFDN001` is accepted only as a possible physical filename alias and maps to
  logical ID `PRFD01N001`; source files are never renamed.
- A schema `PK` marker is preserved. Multiple markers are measured together,
  but composite-key semantics are not asserted.
- Statistical identifier, numeric-like, date-like, enum, and code-like results
  are candidates. They do not establish canonical types or financial meaning.
- Numeric magnitude is never interpreted as percentage, currency, or unit.
- Missing and blank values are measured and are never replaced.
- No PostgreSQL, SQL generation, Vector, Graph, Ontology, tax, embedding, or HCX
  integration is part of G1 profiling.
