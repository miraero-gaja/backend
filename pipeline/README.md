# Data pipeline

The implemented offline pipeline currently has two read-only stages:

- [`profiling/`](profiling/README.md): G1 source discovery, schema/data profiling,
  integrity checks, and aggregate reports.
- [`normalize/`](normalize/README.md): G2-A deterministic typed-staging rules,
  technical row lineage, whitespace-impact evidence, and complete source-column
  coverage mapping.

Neither stage is imported by the FastAPI request path. G2-A does not create a
database or copy source rows. Future ingest, entity-resolution, and indexing
stages remain unimplemented and must define explicit snapshot, lineage,
validation, and rollback contracts before they are added.
