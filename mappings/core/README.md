# G2 Core Field Mapping

This package is the narrow agent-facing allowlist for G2 Structured Baseline.
It is not a replacement for the 207-column Typed Staging registry.

## Evidence boundary

- The four official schema workbooks were extracted read-only and matched the
  G1 schema profile exactly.
- `PREF01N001` has 73 official display names and `PRFD01N001` has 45.
- `PRBD01N001` and `PREF02N001` have no official display-name/description
  values. Their abbreviations and sample values are insufficient evidence, so
  all 89 columns remain unconfirmed for agent field selection.
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

Full alias expansion, unit/currency/rate-scale approval, code-value grounding,
and cross-product ontology unification remain G3 work.
