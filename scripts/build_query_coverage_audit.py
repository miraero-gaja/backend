"""Build the conservative 2026-08-24 query-coverage audit report."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mappings.core import CORE_FIELD_MAPPINGS, SemanticStatus
from mappings.semantic import SEMANTIC_FIELD_APPROVALS
from pipeline.dataset_contract import TOTAL_COLUMNS


SCHEMA_PROFILE = (
    ROOT / "artifacts/profiling/20260824/g1/g1_schema_profile.json"
)
DATA_PROFILE = ROOT / "artifacts/profiling/20260824/g1/g1_data_profile.json"
TYPED_RULES = ROOT / "artifacts/profiling/20260824/g2a/g2a_typed_rules.json"
DEFAULT_OUTPUT = ROOT / "outputs/reports/query_coverage_audit_20260824.json"

_OPERATION_ORDER = {
    operation: index
    for index, operation in enumerate(
        (
            "PROJECT",
            "EQ",
            "NE",
            "LT",
            "LE",
            "GT",
            "GE",
            "SORT",
            "SORT_ASC",
            "SORT_DESC",
            "TEXT_MATCH",
        )
    )
}

# These 15 fields are the deliberately narrow implementation set from this
# audit. All are official TEXT name/category fields and expose only exact
# source-native equality plus projection.
_NEW_CORE_SOURCES = frozenset(
    {
        ("PRBD01N001", "pd_no"),
        ("PRBD01N001", "pd_nm"),
        ("PRBD01N001", "std_pd_mcls_nm"),
        ("PRBD01N001", "std_pd_scls_nm"),
        ("PREF01N001", "cu_fund_mgmt_co"),
        ("PREF01N001", "cu_base_index"),
        ("PREF01N001", "cu_strtegy"),
        ("PREF02N001", "cu_fund_mgmt_co"),
        ("PREF02N001", "cu_base_index"),
        ("PREF02N001", "wu_inv_ast_type"),
        ("PREF02N001", "wu_inv_rgn"),
        ("PRFD01N001", "bmrk_nm"),
        ("PRFD01N001", "han_clas_nm"),
        ("PRFD01N001", "han_clas_sales_channel"),
        ("PRFD01N001", "zrin_ptn_nm"),
    }
)

_UPGRADED_G3_SOURCES = frozenset(
    {
        ("PREF02N001", "pd_itm_no"),
        ("PREF02N001", "pd_nm"),
    }
)

_BASELINE_G3_OPERATIONS = {
    ("PREF02N001", "du_last_aum"): ("PROJECT", "SORT_DESC"),
    ("PREF02N001", "pd_itm_no"): ("PROJECT",),
    ("PREF02N001", "pd_nm"): ("PROJECT",),
}

_DATE_LABEL_MARKERS = (
    "일자",
    "기준일",
    "설정일",
    "발행일",
    "상환일",
)
_NAME_REVIEW_MARKERS = (
    "명",
    "기관",
    "운용사",
    "시장",
    "벤치마크",
    "티커",
    "ISIN",
    "RIC",
    "전략",
    "지역",
    "자산",
    "판매채널",
)
_COUNT_LABEL_MARKERS = ("주식수", "수량", "횟수", "개수")


def _document(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _ordered(operations: set[str] | tuple[str, ...] | list[str]) -> list[str]:
    return sorted(
        set(operations),
        key=lambda item: (_OPERATION_ORDER.get(item, 999), item),
    )


def _core_operations(mapping: Any) -> tuple[str, ...]:
    if mapping.semantic_status is not SemanticStatus.CONFIRMED:
        return ()
    # Core projection is an implicit trusted-field capability in the compiler.
    return ("PROJECT", *mapping.allowed_operations)


def _looks_like_opaque_code(label: str) -> bool:
    if "코드" not in label and "여부" not in label:
        return False
    return "설명" not in label and not label.endswith("명")


def _decision(
    *,
    identity: tuple[str, str],
    label: str,
    target_type: str,
    current_operations: list[str],
    implemented_operations: list[str],
    whitespace_count: int,
) -> tuple[str, list[str], str]:
    if identity == ("PREF02N001", "cu_base_index"):
        return (
            "SAFE_TO_OPEN",
            [],
            (
                "Official schema meaning is an unambiguous TEXT index name. "
                "PROJECT/EQ/NE remain exact for actual source-native names; "
                "the two field-registered SOURCE_NOT_AVAILABLE literals are "
                "NULL_EQUIVALENT and are excluded from semantic execution "
                "and answer evidence without rewriting raw/staging values."
            ),
        )
    if identity in _NEW_CORE_SOURCES:
        return (
            "SAFE_TO_OPEN",
            [],
            (
                "Official schema meaning is an unambiguous TEXT name/category; "
                "runtime uses source-native PROJECT/EQ/NE only, with no trim, "
                "ordering, code interpretation, or cross-product merge."
            ),
        )
    if identity in _UPGRADED_G3_SOURCES:
        return (
            "SAFE_TO_OPEN",
            [],
            (
                "Existing T1/T4 G3 display field now adds exact source-native "
                "EQ/NE; PROJECT remains open and all ordering/range operations "
                "remain closed."
            ),
        )
    if implemented_operations:
        if target_type in {"DECIMAL", "INTEGER"}:
            return (
                "REVIEW_REQUIRED",
                [],
                (
                    "Pre-existing numeric capability is preserved for regression "
                    "compatibility, but no additional operation is approved: the "
                    "official schema declares no unit or scale."
                ),
            )
        if _looks_like_opaque_code(label):
            return (
                "REVIEW_REQUIRED",
                [],
                (
                    "Pre-existing exact raw-token capability is preserved; code "
                    "meaning, ordinal direction, and broader aliases need review."
                ),
            )
        return (
            "SAFE_TO_OPEN",
            [],
            "Existing exact source-native text capability remains evidence-safe.",
        )

    if target_type == "TEXT" and any(
        marker in label for marker in _DATE_LABEL_MARKERS
    ):
        return (
            "REVIEW_REQUIRED",
            ["PROJECT", "EQ", "NE"],
            (
                "Official meaning is date-like but the physical target remains "
                "TEXT; natural-language format normalization and sentinel policy "
                "need human approval. Temporal range/sort stays closed."
            ),
        )
    if target_type in {"DECIMAL", "INTEGER"} and any(
        marker in label for marker in _COUNT_LABEL_MARKERS
    ):
        return (
            "REVIEW_REQUIRED",
            ["PROJECT", "EQ", "NE", "LT", "LE", "GT", "GE", "SORT"],
            (
                "Count meaning is plausible, but unit/value-domain evidence must "
                "be approved independently before numeric operations open."
            ),
        )
    if target_type == "TEXT" and any(
        marker.casefold() in label.casefold() for marker in _NAME_REVIEW_MARKERS
    ):
        whitespace_note = (
            " Source values include leading/trailing whitespace, so no trim or "
            "natural exact-match policy is assumed."
            if whitespace_count
            else ""
        )
        return (
            "REVIEW_REQUIRED",
            ["PROJECT", "EQ", "NE"],
            (
                "Official label identifies a potentially useful text field, but "
                "alias/domain collision review is still required."
                f"{whitespace_note}"
            ),
        )
    if target_type in {"DECIMAL", "INTEGER"}:
        return (
            "KEEP_CLOSED",
            [],
            (
                "Numeric physical type and parseability do not establish concept "
                "unit, scale, value meaning, or an allowed comparison/order."
            ),
        )
    if _looks_like_opaque_code(label):
        return (
            "KEEP_CLOSED",
            [],
            "Raw code/boolean meaning and direction are not officially approved.",
        )
    return (
        "KEEP_CLOSED",
        [],
        (
            "No sufficiently specific, collision-safe deterministic query "
            "capability was justified for this source field in this iteration."
        ),
    )


def build_report() -> dict[str, Any]:
    schema = _document(SCHEMA_PROFILE)
    data = _document(DATA_PROFILE)
    typed = _document(TYPED_RULES)

    data_columns = {
        (table["logical_table_id"], column["qualified_name"]): column
        for table in data["tables"]
        for column in table["columns"]
    }
    typed_rules = {
        (rule["logical_table_id"], rule["qualified_name"]): rule
        for rule in typed["rules"]
    }
    core = {
        (mapping.logical_table_id, mapping.qualified_name): mapping
        for mapping in CORE_FIELD_MAPPINGS
    }
    semantic = {
        (approval.logical_table_id, approval.qualified_name): approval
        for approval in SEMANTIC_FIELD_APPROVALS
    }
    overlap = set(core) & set(semantic)
    if overlap:
        raise RuntimeError(f"core/G3 source authority overlap: {sorted(overlap)}")

    entries: list[dict[str, Any]] = []
    baseline_open_sources: set[tuple[str, str]] = set()
    implemented_open_sources: set[tuple[str, str]] = set()

    for table in schema["tables"]:
        table_id = table["logical_table_id"]
        for schema_column in table["columns"]:
            qualified_name = schema_column["qualified_name"]
            source_column = schema_column["column_name"]
            identity = (table_id, source_column)
            qualified_identity = (table_id, qualified_name)
            data_column = data_columns[qualified_identity]
            typed_rule = typed_rules[qualified_identity]
            core_mapping = core.get(qualified_identity)
            semantic_approval = semantic.get(qualified_identity)

            core_current = (
                _core_operations(core_mapping) if core_mapping is not None else ()
            )
            semantic_current = (
                semantic_approval.open_operations
                if semantic_approval is not None
                else ()
            )
            implemented_operations = _ordered(
                {*core_current, *semantic_current}
            )

            core_baseline = (
                () if identity in _NEW_CORE_SOURCES else core_current
            )
            semantic_baseline = _BASELINE_G3_OPERATIONS.get(identity, ())
            current_operations = _ordered(
                {*core_baseline, *semantic_baseline}
            )
            additional_operations = _ordered(
                set(implemented_operations) - set(current_operations)
            )
            if current_operations:
                baseline_open_sources.add(identity)
            if implemented_operations:
                implemented_open_sources.add(identity)

            semantic_key = None
            semantic_status = "UNMAPPED"
            unit_status = "UNMAPPED"
            if core_mapping is not None:
                semantic_key = core_mapping.semantic_field_key
                semantic_status = core_mapping.semantic_status.value
                unit_status = core_mapping.unit_status.value
            elif semantic_approval is not None:
                semantic_key = semantic_approval.semantic_key
                semantic_status = semantic_approval.concept.status.value
                unit_status = semantic_approval.unit.status.value

            decision, potential, reason = _decision(
                identity=identity,
                label=schema_column["display_name"],
                target_type=typed_rule["target_type"],
                current_operations=current_operations,
                implemented_operations=implemented_operations,
                whitespace_count=int(
                    data_column["leading_or_trailing_whitespace_count"]
                ),
            )
            parse_aggregate = typed_rule["parse_aggregate"]
            entries.append(
                {
                    "decision": decision,
                    "logical_table": table_id,
                    "source_column": source_column,
                    "qualified_name": qualified_name,
                    "official_schema_label_comment": schema_column[
                        "display_name"
                    ],
                    "physical_type": schema_column["declared_type"],
                    "target_type": typed_rule["target_type"],
                    "semantic_key": semantic_key,
                    "concept_evidence": {
                        "status": semantic_status,
                        "basis": (
                            "reviewed runtime registry plus official schema"
                            if semantic_key is not None
                            else "official schema label is a candidate only"
                        ),
                        "artifact": (
                            "artifacts/profiling/20260824/g1/"
                            "g1_schema_profile.json"
                        ),
                    },
                    "unit_evidence": {
                        "status": unit_status,
                        "declared_unit": schema_column["declared_unit"],
                        "basis": (
                            "No official schema unit is declared; text concepts "
                            "may be reviewed as NOT_APPLICABLE, never as evidence "
                            "for a separate numeric field."
                        ),
                    },
                    "domain_evidence": {
                        "row_count": data_column["row_count"],
                        "non_null_count": data_column["non_null_count"],
                        "distinct_count": data_column["distinct_count"],
                        "leading_or_trailing_whitespace_count": data_column[
                            "leading_or_trailing_whitespace_count"
                        ],
                        "date_like_string_candidate": data_column[
                            "date_like_string"
                        ]["candidate"],
                        "code_like_string_candidate": data_column[
                            "code_like_string"
                        ]["candidate"],
                        "parse_error_count": parse_aggregate[
                            "parse_error_count"
                        ],
                        "null_policy": typed_rule["null_policy"],
                        "whitespace_policy": typed_rule[
                            "whitespace_policy"
                        ],
                        "artifacts": [
                            "artifacts/profiling/20260824/g1/"
                            "g1_data_profile.json",
                            "artifacts/profiling/20260824/g2a/"
                            "g2a_typed_rules.json",
                        ],
                    },
                    "current_operations": current_operations,
                    "additional_operations": additional_operations,
                    "implemented_operations": implemented_operations,
                    "potential_operations_after_review": _ordered(potential),
                    "reason": reason,
                }
            )

    if len(entries) != TOTAL_COLUMNS:
        raise RuntimeError(
            f"audit must cover {TOTAL_COLUMNS} columns, got {len(entries)}"
        )
    if len(baseline_open_sources) != 37:
        raise RuntimeError(
            "baseline effective approved-source count drifted: "
            f"{len(baseline_open_sources)}"
        )
    if len(implemented_open_sources) != 52:
        raise RuntimeError(
            "implemented effective approved-source count drifted: "
            f"{len(implemented_open_sources)}"
        )

    decision_counts = dict(sorted(Counter(
        entry["decision"] for entry in entries
    ).items()))
    return {
        "report_kind": "query_coverage_audit",
        "source_snapshot": "2026-08-24",
        "official_column_count": TOTAL_COLUMNS,
        "baseline_effective_approved_field_count": len(
            baseline_open_sources
        ),
        "implemented_effective_approved_field_count": len(
            implemented_open_sources
        ),
        "new_effective_approved_field_count": (
            len(implemented_open_sources) - len(baseline_open_sources)
        ),
        "decision_counts": decision_counts,
        "policy": {
            "concept_is_not_unit_or_domain_or_operation": True,
            "numeric_type_does_not_approve_range_or_sort": True,
            "automatic_trim": False,
            "zero_imputation": False,
            "code_ordering_inferred": False,
            "cross_product_metric_expansion": False,
            "archive_20260711_used_as_current_evidence": False,
        },
        "evidence_sources": [
            "pipeline/dataset_contract.py",
            "artifacts/profiling/20260824/g1/g1_schema_profile.json",
            "artifacts/profiling/20260824/g1/g1_data_profile.json",
            "artifacts/profiling/20260824/g2a/g2a_typed_rules.json",
            "mappings/core/registry.py",
            "mappings/semantic/registry.py",
            "mappings/aliases/registry.py",
            "ontology/*.ttl",
        ],
        "entries": entries,
    }


def main() -> None:
    report = build_report()
    DEFAULT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_OUTPUT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(DEFAULT_OUTPUT.relative_to(ROOT)),
                "columns": len(report["entries"]),
                "decision_counts": report["decision_counts"],
                "approved_before": report[
                    "baseline_effective_approved_field_count"
                ],
                "approved_after": report[
                    "implemented_effective_approved_field_count"
                ],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
