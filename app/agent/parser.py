"""Deterministic lexical parser for the narrow structured-query baseline."""

from __future__ import annotations

import re

from app.agent.contracts import (
    CrossProductScopeQuery,
    CrossProductUnderstanding,
    ParsedFilterCondition,
    QueryContract,
    QueryUnderstandingResult,
    QueryUnderstandingStatus,
    RouteHint,
)
from app.structured.contracts import (
    AggregateFunction,
    FilterOperator,
    SortDirection,
)
from mappings.aliases import field_alias_matches, product_alias_matches
from mappings.core import SemanticStatus, get_confirmed_field_map
from mappings.semantic import get_semantic_field_approval


_COMPARATORS = {
    "이상": FilterOperator.GE,
    "이하": FilterOperator.LE,
    "초과": FilterOperator.GT,
    "미만": FilterOperator.LT,
}
_EXPLICIT_TOP_N = re.compile(r"(?:top|상위)\s*(\d+)\s*개?", re.IGNORECASE)
_COUNT_INTENT = re.compile(r"(?:총\s*)?(?:몇\s*개|개수)")
_DESCENDING = re.compile(
    r"(?:큰\s*(?:순서|순|상품)|높은\s*순|내림차순)",
    re.IGNORECASE,
)
_ASCENDING = re.compile(
    r"(?:작은\s*(?:순서|순|상품)|낮은\s*순|오름차순)",
    re.IGNORECASE,
)
_TRAILING_COUNT = re.compile(r"(\d+)\s*개")


def _spaced_alias_pattern(alias: str) -> str:
    return r"\s*".join(re.escape(character) for character in alias)


def _parse_filter(
    question: str,
    field_alias: str,
    *,
    eq_approved: bool,
) -> ParsedFilterCondition | None:
    alias_pattern = _spaced_alias_pattern(field_alias)
    threshold = re.search(
        rf"{alias_pattern}\s*(?:이|가|은|는)?\s*"
        rf"([+-]?\d+(?:\.\d+)?)\s*(억|만|%|퍼센트)?\s*"
        rf"(이상|이하|초과|미만)",
        question,
        re.IGNORECASE,
    )
    if threshold is not None:
        return ParsedFilterCondition(
            field_alias=field_alias,
            operator=_COMPARATORS[threshold.group(3)],
            value=threshold.group(1),
            unit_token=threshold.group(2),
        )

    if field_alias == "상품코드":
        equality = re.search(
            rf"{alias_pattern}\s*(?:이|가|은|는)?\s*"
            rf"(?:=|같은|동일한)?\s*([A-Za-z0-9._-]+)",
            question,
            re.IGNORECASE,
        )
        if equality is not None:
            return ParsedFilterCondition(
                field_alias=field_alias,
                operator=FilterOperator.EQ,
                value=equality.group(1),
            )
    if eq_approved:
        for suffix in (
            r"(?:과|와)\s*(?:같은|동일한)\s*(?:상품|것)",
            r"인\s*(?:상품|것)",
        ):
            equality = re.search(
                rf"{alias_pattern}\s*(?:이|가|은|는)?\s*"
                rf"(.+?)\s*{suffix}",
                question,
                re.IGNORECASE,
            )
            if equality is not None and equality.group(1).strip():
                return ParsedFilterCondition(
                    field_alias=field_alias,
                    operator=FilterOperator.EQ,
                    value=equality.group(1).strip(),
                )
    return None


def _eq_operation_is_open(
    logical_table_id: str,
    semantic_keys: tuple[str, ...],
) -> bool:
    """Mirror grounder precedence when deciding whether text EQ may parse."""

    core_fields = get_confirmed_field_map(logical_table_id)
    for semantic_key in semantic_keys:
        semantic_approval = get_semantic_field_approval(
            logical_table_id,
            semantic_key,
        )
        if semantic_approval is not None:
            if "EQ" in semantic_approval.open_operations:
                return True
            continue
        mapping = core_fields.get(semantic_key)
        if (
            mapping is not None
            and mapping.semantic_status is SemanticStatus.CONFIRMED
            and "EQ" in mapping.allowed_operations
        ):
            return True
    return False


class QueryParser:
    """Extract only explicit product, field, comparison, sort, and Top-N tokens."""

    def _try_cross_product(
        self,
        *,
        request_id: str,
        question_id: str,
        question: str,
        products: tuple,
    ) -> QueryContract | None:
        """Detect a deterministic cross-product COUNT intent, if any.

        Returns None when the question does not qualify -- callers must
        then fall through to the existing single-product (or ambiguous
        multi-scope) handling unchanged. Qualification is structural, not
        tied to any specific product pair or golden query text:
        - 2+ distinct matched product scopes
        - an explicit COUNT intent token
        - no field-specific alias hit for any matched scope (a
          field-specific question about multiple products stays
          multiple_product_scopes/AMBIGUOUS, since per-field comparability
          across scopes is not established here).
        """

        seen: dict[str, object] = {}
        for product in products:
            seen.setdefault(product.logical_table_id, product)
        distinct_products = tuple(seen.values())
        if len(distinct_products) < 2:
            return None
        if _COUNT_INTENT.search(question) is None:
            return None
        if any(
            field_alias_matches(product.logical_table_id, question)
            for product in distinct_products
        ):
            return None

        trace = [
            f"cross-product 상품군: {product.display_name} → {product.logical_table_id}"
            for product in distinct_products
        ]
        trace.append("cross-product 집계 의도: COUNT")
        scopes = tuple(
            CrossProductScopeQuery(
                product_candidate=product.display_name,
                logical_table_id=product.logical_table_id,
            )
            for product in distinct_products
        )
        cross_product = CrossProductUnderstanding(
            metric=AggregateFunction.COUNT,
            scopes=scopes,
            status=QueryUnderstandingStatus.PARSED,
            execution_trace=tuple(trace),
        )
        return QueryContract(
            request_id=request_id,
            question_id=question_id,
            product_scopes=tuple(product.logical_table_id for product in distinct_products),
            semantic_intent="deterministic_cross_product_candidate",
            route_hint=RouteHint.UNSUPPORTED,
            cross_product=cross_product,
        )

    def parse(
        self,
        *,
        request_id: str,
        question_id: str,
        question: str,
    ) -> QueryContract:
        missing_inputs = tuple(
            name
            for name, value in (("question_id", question_id), ("question", question))
            if not value.strip()
        )
        if missing_inputs:
            understanding = QueryUnderstandingResult(
                status=QueryUnderstandingStatus.UNSUPPORTED,
                unsupported_reason="required_input_missing",
                execution_trace=("필수 입력 확인: 실패",),
            )
            return QueryContract(
                request_id=request_id,
                question_id=question_id,
                required_inputs=missing_inputs,
                ambiguity=(),
                route_hint=RouteHint.UNSUPPORTED,
                understanding=understanding,
            )

        trace: list[str] = []
        ambiguity: list[str] = []
        products = product_alias_matches(question)
        if len(products) >= 2:
            cross_product_contract = self._try_cross_product(
                request_id=request_id,
                question_id=question_id,
                question=question,
                products=products,
            )
            if cross_product_contract is not None:
                return cross_product_contract
        if len(products) != 1:
            reason = (
                "product_scope_missing"
                if not products
                else "multiple_product_scopes"
            )
            ambiguity.append(reason)
            trace.append(f"상품군 파싱: {reason}")
            understanding = QueryUnderstandingResult(
                status=QueryUnderstandingStatus.AMBIGUOUS,
                ambiguity=tuple(ambiguity),
                execution_trace=tuple(trace),
            )
            return QueryContract(
                request_id=request_id,
                question_id=question_id,
                ambiguity=tuple(ambiguity),
                route_hint=RouteHint.UNSUPPORTED,
                understanding=understanding,
            )

        product = products[0]
        trace.append(
            f"상품군: {product.display_name} → {product.logical_table_id}"
        )
        fields = field_alias_matches(product.logical_table_id, question)
        aggregate = (
            AggregateFunction.COUNT if _COUNT_INTENT.search(question) else None
        )
        if len(fields) > 1:
            ambiguity.append("multiple_semantic_fields")
        if ambiguity:
            trace.append("필드 파싱: multiple_semantic_fields")
            understanding = QueryUnderstandingResult(
                product_candidate=product.display_name,
                logical_table_id=product.logical_table_id,
                status=QueryUnderstandingStatus.AMBIGUOUS,
                ambiguity=tuple(ambiguity),
                aggregate=aggregate,
                execution_trace=tuple(trace),
            )
            return QueryContract(
                request_id=request_id,
                question_id=question_id,
                product_scopes=(product.logical_table_id,),
                ambiguity=tuple(ambiguity),
                route_hint=RouteHint.UNSUPPORTED,
                understanding=understanding,
            )

        if not fields and aggregate is None:
            trace.append("필드 파싱: 인식 실패")
            understanding = QueryUnderstandingResult(
                product_candidate=product.display_name,
                logical_table_id=product.logical_table_id,
                status=QueryUnderstandingStatus.UNSUPPORTED,
                unsupported_reason="semantic_field_not_recognized",
                execution_trace=tuple(trace),
            )
            return QueryContract(
                request_id=request_id,
                question_id=question_id,
                product_scopes=(product.logical_table_id,),
                semantic_intent="deterministic_structured_candidate",
                ambiguity=(),
                route_hint=RouteHint.UNSUPPORTED,
                understanding=understanding,
            )

        field_alias = fields[0].alias if fields else None
        if field_alias is not None:
            trace.append(f"필드 표현: {field_alias}")
        condition = (
            _parse_filter(
                question,
                field_alias,
                eq_approved=_eq_operation_is_open(
                    product.logical_table_id,
                    fields[0].semantic_keys,
                ),
            )
            if field_alias is not None
            else None
        )

        explicit_top_match = _EXPLICIT_TOP_N.search(question)
        descending = (
            _DESCENDING.search(question) is not None
            or explicit_top_match is not None
        )
        ascending = _ASCENDING.search(question) is not None
        if descending and ascending:
            ambiguity.append("sort_direction_conflict")
            sort_direction = None
        elif descending:
            sort_direction = SortDirection.DESC
            trace.append("정렬 표현: DESC")
        elif ascending:
            sort_direction = SortDirection.ASC
            trace.append("정렬 표현: ASC")
        else:
            sort_direction = None

        top_match = explicit_top_match
        if top_match is None and sort_direction is not None:
            top_match = _TRAILING_COUNT.search(question)
        limit = int(top_match.group(1)) if top_match is not None else None
        if limit is not None:
            if limit < 1 or limit > 100:
                understanding = QueryUnderstandingResult(
                    product_candidate=product.display_name,
                    logical_table_id=product.logical_table_id,
                    requested_field_alias=field_alias,
                    filter_conditions=((condition,) if condition else ()),
                    sort_direction=sort_direction,
                    status=QueryUnderstandingStatus.UNSUPPORTED,
                    unsupported_reason="top_n_out_of_range",
                    execution_trace=tuple((*trace, "Top-N 범위: 지원하지 않음")),
                )
                return QueryContract(
                    request_id=request_id,
                    question_id=question_id,
                    product_scopes=(product.logical_table_id,),
                    ambiguity=(),
                    route_hint=RouteHint.UNSUPPORTED,
                    understanding=understanding,
                )
            trace.append(f"Top-N: {limit}")

        if ambiguity:
            understanding = QueryUnderstandingResult(
                product_candidate=product.display_name,
                logical_table_id=product.logical_table_id,
                requested_field_alias=field_alias,
                filter_conditions=((condition,) if condition else ()),
                limit=limit,
                aggregate=aggregate,
                status=QueryUnderstandingStatus.AMBIGUOUS,
                ambiguity=tuple(ambiguity),
                execution_trace=tuple(trace),
            )
            return QueryContract(
                request_id=request_id,
                question_id=question_id,
                product_scopes=(product.logical_table_id,),
                ambiguity=tuple(ambiguity),
                route_hint=RouteHint.UNSUPPORTED,
                understanding=understanding,
            )

        understanding = QueryUnderstandingResult(
            product_candidate=product.display_name,
            logical_table_id=product.logical_table_id,
            requested_field_alias=field_alias,
            semantic_keys=(fields[0].semantic_keys if fields else ()),
            filter_conditions=((condition,) if condition else ()),
            sort_direction=sort_direction,
            limit=limit,
            aggregate=aggregate,
            status=QueryUnderstandingStatus.PARSED,
            execution_trace=tuple(trace),
        )
        return QueryContract(
            request_id=request_id,
            question_id=question_id,
            product_scopes=(product.logical_table_id,),
            semantic_intent="deterministic_structured_candidate",
            route_hint=RouteHint.UNSUPPORTED,
            understanding=understanding,
        )
