# Coverage registry

`build_coverage_registry(schema_profile, data_profile, ...)` joins G1 schema
and data profiles by `(logical_table_id, qualified_name)`. `qualified_name`
contains the header occurrence number, so duplicate source headers are not
collapsed.

The active official four-table dataset is validated against 280 actual columns and
requires exact schema/data identity and order. Every coverage entry contains
source identity, declared type, non-null ratio, conservative identifier role,
typed/concept/unit/code status, supported operations, and review notes.

Optional typed-rule, parse-aggregate, and whitespace-aggregate records use the
same occurrence-aware identity. `typed_status` is technical readiness and is
kept separate from concept `mapping_status`: it is one of `READY`,
`PARSE_REVIEW_REQUIRED`, `UNSUPPORTED`, or `UNASSESSED`. Supported operations
remain empty unless a target type is supported and explicit aggregate evidence
records zero parse errors. `AGGREGATE` additionally requires confirmed concept
and unit evidence; none is asserted from the current G1 profiles.

No raw source values, database objects, SQL engine, graph, vector index, or
ontology artifact is created here.
