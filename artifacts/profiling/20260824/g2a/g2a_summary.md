# G2-A Typed Staging Specification and Coverage Summary

- G2-A status: **PASS**
- Source rows verified: 53,375
- Typed rules: 280
- Coverage: 280/280 (100%)
- Parse errors: 0
- Source immutable check: PASS
- Scope: deterministic Raw → Typed Staging → Coverage contract only; no database or query engine was created.

## Target type distribution

| Target type | Columns |
|---|---:|
| DECIMAL | 115 |
| INTEGER | 1 |
| TEXT | 164 |

## Mapping review

- CONFIRMED: 0
- CANDIDATE: 280
- UNMAPPED: 0
- Official schema display names are review labels only. No canonical cross-table concept was confirmed.

## Parse and null policy

- OK: 2,508,076
- MISSING: 982,932
- EMPTY: 0
- WHITESPACE_ONLY: 24,101
- PARSE_ERROR: 0
- NOT_APPLICABLE: 0

## Whitespace review

- Columns with hypothetical trim collisions: 4
- Conflict columns: PRBD01N001.bd_knd#1, PRBD01N001.pd_pbcm#1, PREF01N001.pd_mkt_nm#1, PRFD01N001.mtco_itm_no#1
- Identifier columns whose uniqueness changes: none
- Automatic trim applied: false

## Source row lineage

- Algorithm: SHA-256 over a domain/version prefix and unsigned 8-byte length-prefixed UTF-8 components
- Version: v1
- Inputs: logical table, source file SHA-256, source sheet, source Excel row.
- source_row_id is technical lineage and is never treated as a business primary key.

## G2-B review blockers

- Choose an explicit preserve/trim rule for the 4 columns where hypothetical trim collapses distinct raw values.
- Decide business-key policy for PREF01 only after reviewing its declared key component blank count (0); G2-A does not enforce it as a primary key.
- Approve a canonical concept vocabulary and manually review 280 candidates and 0 unmapped fields; G2-A confirms none.
- Provide official units/currencies/percentage semantics; G1 declares units for 0 columns, so unit-based aggregation remains disabled.

## Guardrails

- Raw values are preserved by the row-local ParseResult contract but are not copied into these aggregate reports.
- Missing, empty, whitespace-only, parse-error, and unsupported results remain distinguishable.
- Numeric-looking text is not converted unless its official schema type is numeric.
- Units, currencies, percentages, code meanings, and cross-table financial concepts are not inferred.
- No PostgreSQL, SQL engine, NL2SQL, Vector, Graph, Ontology TTL, HCX, tax, or external data integration is included.
