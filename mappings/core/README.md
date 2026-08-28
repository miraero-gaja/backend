# G2 Core Field Mapping

This package is the narrow agent-facing allowlist for G2 Structured Baseline.
It is not a replacement for the 280-column Typed Staging registry.

## Evidence boundary

- The active physical dataset contract is the 2026-08-24 four-table release.
- The query-coverage expansion is limited to reviewed source-native text
  identifiers, names, and categories from the active official schema/data.
  New fields expose projection and exact `EQ/NE` only.
- Semantic keys are table-scoped. Similar fields in ETF and fund tables are
  not declared to be one canonical concept.

## Query boundary

Only `CONFIRMED` entries returned by `get_confirmed_field_map()` may be exposed
to the Structured Tool. A field may exist in PostgreSQL without being present
in this allowlist.

Numeric values are never unit- or scale-converted. Returns, AUM, and net assets
have explicit meanings but no declared unit, so only source-native `SORT` is
approved. `PREF01N001.pd_lst_stk_cnt` additionally permits numeric comparisons
because the official description explicitly identifies a share count and the
schema declares it numeric; its source-native scale is still preserved.

The cost fields and two date-like fields are retained as `NEED_REVIEW` with no
operations because their official target type is `TEXT` and no safe numeric or
temporal conversion is declared.

`PREF02N001.cu_base_index` has one field-specific exception to the general
source-native text policy. `Index is not provided by Management Company` and
`Index is not available on Lipper Database` are registered as
`SOURCE_NOT_AVAILABLE` / `NULL_EQUIVALENT`. Raw and staging values remain
unchanged; semantic projection/evidence omits those rows, and exact `EQ/NE`
continues only for actual index names. This policy does not apply to any other
field and does not convert numeric zero or database `NULL`.

Unit/currency/rate-scale approval, code-value grounding, date normalization,
free-text matching, and cross-product ontology unification remain closed.
