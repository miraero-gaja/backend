# Data pipeline

The implemented data path currently has three stages:

- [`profiling/`](profiling/README.md): G1 source discovery, schema/data profiling,
  integrity checks, and aggregate reports.
- [`normalize/`](normalize/README.md): G2-A deterministic typed-staging rules,
  technical row lineage, whitespace-impact evidence, and complete source-column
  coverage mapping.
- [`structured/`](structured/README.md): G2-B PostgreSQL staging schema and
  streaming loader, Priority-A allowlist linkage, parameterized query
  validation, and offline/live validation reports.

The G1 and G2-A stages remain read-only. G2-B writes only when an operator
explicitly supplies `DATABASE_URL` and requests a live load; otherwise it runs
the same source/schema/query validation without touching PostgreSQL. The public
FastAPI parser does not create structured plans yet, so `/answer` remains
fail-closed. Entity-resolution and indexing remain unimplemented.
