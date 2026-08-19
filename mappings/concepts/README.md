# Concept candidate registry

This directory contains the conservative G2-A source-to-concept registry.

`build_concept_registry(schema_profile)` emits one occurrence-aware entry for
every official schema column. An official schema display name is preserved as
a `CANDIDATE` label only. If the display name is absent, the field is
`UNMAPPED`. G2-A has no canonical concept vocabulary, so this registry never
emits `CONFIRMED` and never merges similarly named fields across product
groups.

The registry contains metadata only. It does not copy raw rows or infer
financial meaning, units, currencies, percentages, aliases, or ontology terms.
