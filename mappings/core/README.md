# G2 Core Field Mapping

This package is the narrow agent-facing allowlist for G2 Structured Baseline.
It is not a replacement for the 280-column Typed Staging registry.

## Evidence boundary

- The active physical dataset contract is the 2026-08-24 four-table release.
- Existing Priority A semantic approvals are intentionally not expanded by the
  physical-shape migration. They require separate G1 evidence regeneration and
  semantic review before any new field or operation can be approved.
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
