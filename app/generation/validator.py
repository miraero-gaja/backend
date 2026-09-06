"""Conservative deterministic validation of model-generated answers."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .contracts import (
    GenerationInput,
    GenerationValidationReason,
    GenerationValidationStatus,
)
from .prompts import EvidenceOnlyPrompt, EvidencePlaceholder


_PLACEHOLDER = re.compile(r"\{\{(?:E\d{3}|NUM_\d{3})\}\}")
_PLACEHOLDER_CANDIDATE = re.compile(r"\{\{[^{}\r\n]{1,64}\}\}")
_MARKDOWN_JSON_WRAPPER = re.compile(
    r"\A```(?:json)?[ \t]*\r?\n(?P<body>.*)\r?\n```\Z",
    re.IGNORECASE | re.DOTALL,
)
_NUMBER = re.compile(
    r"(?<![A-Za-z0-9_])[-+]?\d+(?:,\d{3})*(?:\.\d+)?(?![A-Za-z0-9_])"
)
_RESULT_COUNT = re.compile(r"\s*(?:개|건|종)(?:의|를|가|는|은|을|로|입니다|입니다\.)?")
_LIST_ENUMERATION = re.compile(
    r"(?m)(?:^|(?<=\\n))[ \t]*(?P<number>\d+)[.)](?!\d)[ \t]*"
)
_INLINE_LIST_ENUMERATION = re.compile(
    r"(?<!\S)(?P<number>\d+)[.)](?!\d)[ \t]*(?=\S)"
)
_INLINE_LIST_INTRO_TERMINATORS = frozenset(".!?:。")
_LOGICAL_LINE_SEPARATOR = re.compile(r"\r\n|\r|\n|\\r\\n|\\r|\\n")
_NUMBER_CONTEXT_RADIUS = 20
_NUMBER_RULE = "EVIDENCE_DERIVED_NUMBER_V1"
_IDENTIFIER = re.compile(r"\b(?=[A-Za-z0-9._-]*[A-Za-z])(?=[A-Za-z0-9._-]*\d)[A-Za-z0-9._-]+\b")
_FINANCIAL_UNIT = re.compile(
    r"(?<![가-힣A-Za-z])(?:퍼센트|억원|백만원|만원|천원|원|억|%)"
    r"(?=$|[\s.,;:!?)]|은|는|이|가|을|를|으로|입니다)"
)
_RECOMMENDATION = re.compile(
    r"추천|투자\s*(?:하세요|권유|권합니다)|매수|매도|선택하세요|권합니다"
)
_NAME_MARKER = re.compile(r"상품명\[([^\]]*)\]")
_IDENTIFIER_MARKER = re.compile(r"상품ID\[([^\]]*)\]")
_EXPLICIT_ENTITY_LABEL = re.compile(r"(?:상품명|상품ID|상품번호)\s*[:=]")
_MARKER_STRUCTURE = re.compile(r"[\s()\-–—/]*")
_PLACEHOLDER_PATTERN = r"\{\{(?:E\d{3}|NUM_\d{3})\}\}"
_NAME_IDENTIFIER_PAIR = re.compile(
    rf"(?P<name>{_PLACEHOLDER_PATTERN})\s*\(\s*"
    rf"(?P<identifier>{_PLACEHOLDER_PATTERN})\s*\)"
)
_IDENTIFIER_NAME_PAIR = re.compile(
    rf"(?P<identifier>{_PLACEHOLDER_PATTERN})\s*[-–—]\s*"
    rf"(?P<name>{_PLACEHOLDER_PATTERN})"
)
_MARKED_NAME_IDENTIFIER_PAIR = re.compile(
    rf"상품명\[(?P<name>{_PLACEHOLDER_PATTERN})\]\s*\(\s*"
    rf"상품ID\[(?P<identifier>{_PLACEHOLDER_PATTERN})\]\s*\)"
)
_EXPLICIT_NAME_MARKER = re.compile(
    rf"상품명\s*[:=]\s*(?P<name>{_PLACEHOLDER_PATTERN})"
    rf"(?:\s*\(\s*(?P<identifier>{_PLACEHOLDER_PATTERN})\s*\))?"
)
_EXPLICIT_IDENTIFIER_MARKER = re.compile(
    rf"(?:상품ID|상품번호)\s*[:=]\s*"
    rf"(?P<identifier>{_PLACEHOLDER_PATTERN})"
    rf"(?:\s*[-–—]\s*(?P<name>{_PLACEHOLDER_PATTERN}))?"
)
_ENTITY_MARKER_RULE = "ENTITY_MARKER_ROLE_AND_PRODUCT_PAIR_V2"
_UNMARKED_PRODUCT_REFERENCE = re.compile(
    r"[가-힣A-Za-z][가-힣A-Za-z0-9&._-]*"
    r"(?:\s+[가-힣A-Za-z0-9&._-]+){0,3}\s*(?:ETF|펀드|채권)"
    r"(?=$|[\s,.;:!?)]|은|는|이|가|을|를|의|에서)"
)
_GENERIC_PRODUCT_REFERENCE = re.compile(
    r"(?:(?:해당|이들|각|상위|하위|모든|전체|세)\s+)?"
    r"(?:(?:상품|상품들)(?:은|는|이|가)?\s+)?"
    r"(?:모두\s+)?(?:국내|해외|글로벌)?\s*(?:ETF|펀드|채권)"
)
_EVIDENCE_DERIVED_INDEX_REFERENCE = re.compile(
    r"(?<![A-Za-z0-9&._-])(?:[A-Za-z]+&)+[A-Za-z]+"
    r"(?:\s+\d+(?:[.,]\d+)*)+(?![A-Za-z0-9&._-])"
)
_UPPERCASE_REFERENCE = re.compile(
    r"(?<![가-힣A-Za-z0-9_])[A-Z]{2,6}(?![가-힣A-Za-z0-9_])"
)
_GENERIC_UPPERCASE_REFERENCES = frozenset({"AUM", "ETF", "KRW", "NAV", "USD"})
_UNMARKED_PRODUCT_REFERENCE_RULE = "UNMARKED_PRODUCT_REFERENCE_V2"
_UNSUPPORTED_FINANCIAL_CLAIM = re.compile(
    r"수익률|수익성|전망|예상|보장|저평가|고평가|투자매력|"
    r"안전(?:하다|합니다|한)|우수(?:하다|합니다|한)|유리(?:하다|합니다|한)|"
    r"상승(?:한다|합니다|할)|하락(?:한다|합니다|할)"
)
_ENTITY_CONTINUATION = frozenset("&._-")
_ENTITY_SUFFIXES = (
    "으로부터",
    "에게서",
    "에서는",
    "으로는",
    "입니다",
    "이며",
    "이고",
    "에서",
    "으로",
    "부터",
    "까지",
    "처럼",
    "보다",
    "에게",
    "한테",
    "께서",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "의",
    "와",
    "과",
    "도",
    "만",
    "로",
)


@dataclass(frozen=True, slots=True)
class MarkerMismatch:
    marker_token: str
    placeholder_id: str
    declared_role: str
    expected_role: str
    actual_role: str
    mapped_evidence_value: str
    source_row_id: str | None
    product_key: str | None
    structural_context: str
    detection_rule: str


@dataclass(frozen=True, slots=True)
class NumberContext:
    span: str
    start_index: int
    end_index: int
    structural_context: str
    line_index: int
    line_prefix: str
    line_length: int
    is_list_candidate: bool
    candidate_rejection_reason: str | None


@dataclass(frozen=True, slots=True)
class PostGenerationValidation:
    status: GenerationValidationStatus
    answer: str | None = None
    reason: GenerationValidationReason | None = None
    normalized_entity_literals: tuple[str, ...] = ()
    residual_entity_literals: tuple[str, ...] = ()
    unmarked_product_reference_spans: tuple[str, ...] = ()
    unmarked_product_reference_normalized_spans: tuple[str, ...] = ()
    unmarked_product_reference_classifications: tuple[str, ...] = ()
    unmarked_product_reference_evidence_sources: tuple[tuple[str, ...], ...] = ()
    unmarked_product_reference_rule: str | None = None
    detected_number_spans: tuple[str, ...] = ()
    normalized_number_spans: tuple[str, ...] = ()
    number_classifications: tuple[str, ...] = ()
    allowed_evidence_numeric_values: tuple[str, ...] = ()
    allowed_derived_numeric_values: tuple[str, ...] = ()
    number_contexts: tuple[NumberContext, ...] = ()
    enumeration_candidate_sequence: tuple[str, ...] = ()
    number_rule: str | None = None
    marker_mismatches: tuple[MarkerMismatch, ...] = ()
    marker_rule: str | None = None

    @property
    def accepted(self) -> bool:
        return self.status is GenerationValidationStatus.ACCEPTED


def _placeholder_map(
    prompt: EvidenceOnlyPrompt,
) -> dict[str, EvidencePlaceholder]:
    return {placeholder.token: placeholder for placeholder in prompt.placeholders}


def _normalize_nonsemantic_wrapper(
    raw_output: str,
) -> tuple[str, GenerationValidationReason | None]:
    candidate = raw_output.strip().lstrip("\ufeff")
    match = _MARKDOWN_JSON_WRAPPER.fullmatch(candidate)
    if match is None:
        return candidate, None
    return match.group("body").strip(), GenerationValidationReason.MARKDOWN_JSON_WRAPPER


def _marker_mismatch(
    token: str,
    *,
    declared_role: str,
    expected_role: str,
    placeholders: dict[str, EvidencePlaceholder],
    structural_context: str,
    detection_rule: str,
) -> MarkerMismatch:
    placeholder = placeholders.get(token)
    return MarkerMismatch(
        marker_token=token,
        placeholder_id=token.removeprefix("{{").removesuffix("}}"),
        declared_role=declared_role,
        expected_role=expected_role,
        actual_role=placeholder.role if placeholder is not None else "unknown",
        mapped_evidence_value=placeholder.value if placeholder is not None else "",
        source_row_id=placeholder.source_row_id if placeholder is not None else None,
        product_key=placeholder.product_key if placeholder is not None else None,
        structural_context=structural_context[:160],
        detection_rule=detection_rule,
    )


def _same_product_pair(
    name: EvidencePlaceholder,
    identifier: EvidencePlaceholder,
) -> bool:
    return bool(
        name.product_key
        and name.product_key == identifier.product_key
        and name.source_row_id
        and name.source_row_id == identifier.source_row_id
    )


def _marker_mismatches(
    template: str,
    placeholders: dict[str, EvidencePlaceholder],
) -> tuple[MarkerMismatch, ...]:
    mismatches: list[MarkerMismatch] = []
    for marker, declared_role in (
        (_NAME_MARKER, "product_name"),
        (_IDENTIFIER_MARKER, "product_identifier"),
    ):
        for match in marker.finditer(template):
            content = match.group(1)
            tokens = tuple(_PLACEHOLDER.findall(content))
            remaining_structure = _PLACEHOLDER.sub("", content)
            if (
                not tokens
                or len(tokens) > 2
                or _MARKER_STRUCTURE.fullmatch(remaining_structure) is None
            ):
                mismatches.append(
                    _marker_mismatch(
                        tokens[0] if tokens else content[:64],
                        declared_role=declared_role,
                        expected_role=declared_role,
                        placeholders=placeholders,
                        structural_context=match.group(0),
                        detection_rule="MARKER_STRUCTURE_INVALID",
                    )
                )
                continue

            expected_roles = (
                (declared_role,)
                if len(tokens) == 1
                else (
                    ("product_name", "product_identifier")
                    if declared_role == "product_name"
                    else ("product_identifier", "product_name")
                )
            )
            for token, expected_role in zip(tokens, expected_roles, strict=True):
                placeholder = placeholders.get(token)
                if placeholder is None or placeholder.role != expected_role:
                    mismatches.append(
                        _marker_mismatch(
                            token,
                            declared_role=declared_role,
                            expected_role=expected_role,
                            placeholders=placeholders,
                            structural_context=match.group(0),
                            detection_rule="MARKER_ROLE_MISMATCH",
                        )
                    )
            if len(tokens) == 2:
                first = placeholders.get(tokens[0])
                second = placeholders.get(tokens[1])
                if (
                    first is not None
                    and second is not None
                    and first.role == expected_roles[0]
                    and second.role == expected_roles[1]
                ):
                    name = first if first.role == "product_name" else second
                    identifier = (
                        first if first.role == "product_identifier" else second
                    )
                    if not _same_product_pair(name, identifier):
                        mismatches.append(
                            _marker_mismatch(
                                identifier.token,
                                declared_role=declared_role,
                                expected_role="same_product_identifier",
                                placeholders=placeholders,
                                structural_context=match.group(0),
                                detection_rule="PRODUCT_PAIR_MISMATCH",
                            )
                        )

    pair_patterns = (
        _NAME_IDENTIFIER_PAIR,
        _IDENTIFIER_NAME_PAIR,
        _MARKED_NAME_IDENTIFIER_PAIR,
    )
    for pattern in pair_patterns:
        for match in pattern.finditer(template):
            name_token = match.group("name")
            identifier_token = match.group("identifier")
            name = placeholders.get(name_token)
            identifier = placeholders.get(identifier_token)
            for token, expected_role in (
                (name_token, "product_name"),
                (identifier_token, "product_identifier"),
            ):
                placeholder = placeholders.get(token)
                if placeholder is None or placeholder.role != expected_role:
                    mismatches.append(
                        _marker_mismatch(
                            token,
                            declared_role="product_pair",
                            expected_role=expected_role,
                            placeholders=placeholders,
                            structural_context=match.group(0),
                            detection_rule="PAIR_ROLE_MISMATCH",
                        )
                    )
            if (
                name is not None
                and identifier is not None
                and name.role == "product_name"
                and identifier.role == "product_identifier"
                and not _same_product_pair(name, identifier)
            ):
                mismatches.append(
                    _marker_mismatch(
                        identifier_token,
                        declared_role="product_pair",
                        expected_role="same_product_identifier",
                        placeholders=placeholders,
                        structural_context=match.group(0),
                        detection_rule="PRODUCT_PAIR_MISMATCH",
                    )
                )

    approved_explicit_spans: list[tuple[int, int]] = []
    for pattern, declared_role in (
        (_EXPLICIT_NAME_MARKER, "product_name"),
        (_EXPLICIT_IDENTIFIER_MARKER, "product_identifier"),
    ):
        for match in pattern.finditer(template):
            approved_explicit_spans.append(match.span())
            name_token = match.groupdict().get("name")
            identifier_token = match.groupdict().get("identifier")
            declared_token = (
                name_token if declared_role == "product_name" else identifier_token
            )
            declared_placeholder = (
                placeholders.get(declared_token) if declared_token is not None else None
            )
            if (
                declared_token is None
                or declared_placeholder is None
                or declared_placeholder.role != declared_role
            ):
                mismatches.append(
                    _marker_mismatch(
                        declared_token or match.group(0),
                        declared_role=declared_role,
                        expected_role=declared_role,
                        placeholders=placeholders,
                        structural_context=match.group(0),
                        detection_rule="MARKER_ROLE_MISMATCH",
                    )
                )
            if name_token is not None and identifier_token is not None:
                name = placeholders.get(name_token)
                identifier = placeholders.get(identifier_token)
                if (
                    name is None
                    or identifier is None
                    or name.role != "product_name"
                    or identifier.role != "product_identifier"
                    or not _same_product_pair(name, identifier)
                ):
                    mismatches.append(
                        _marker_mismatch(
                            identifier_token,
                            declared_role=declared_role,
                            expected_role="same_product_identifier",
                            placeholders=placeholders,
                            structural_context=match.group(0),
                            detection_rule="PRODUCT_PAIR_MISMATCH",
                        )
                    )

    for explicit_label in _EXPLICIT_ENTITY_LABEL.finditer(template):
        if not any(
            start <= explicit_label.start() < end
            for start, end in approved_explicit_spans
        ):
            mismatches.append(
                _marker_mismatch(
                    explicit_label.group(0),
                    declared_role="explicit_entity_label",
                    expected_role="approved_role_placeholder",
                    placeholders=placeholders,
                    structural_context=explicit_label.group(0),
                    detection_rule="UNAPPROVED_ENTITY_LABEL",
                )
            )
    return tuple(dict.fromkeys(mismatches))


def _normalize_evidence_entity_literals(
    template: str,
    placeholders: dict[str, EvidencePlaceholder],
) -> tuple[str, tuple[str, ...]]:
    """Replace exact allowed entity literals outside existing placeholders."""

    literal_tokens: dict[str, str] = {}
    for placeholder in placeholders.values():
        if placeholder.role not in {"product_name", "product_identifier"}:
            continue
        normalized = unicodedata.normalize("NFKC", placeholder.value).strip()
        if normalized:
            literal_tokens.setdefault(normalized, placeholder.token)
    if not literal_tokens:
        return template, ()

    alternatives = "|".join(
        re.escape(value)
        for value in sorted(literal_tokens, key=len, reverse=True)
    )
    entity_pattern = re.compile(rf"(?P<entity>{alternatives})")
    normalized_template = unicodedata.normalize("NFKC", template)
    normalized_literals: list[str] = []

    def is_continuation(character: str) -> bool:
        return character.isalnum() or character in _ENTITY_CONTINUATION

    def has_approved_boundary(match: re.Match[str], segment: str) -> bool:
        if match.start() and is_continuation(segment[match.start() - 1]):
            return False
        if match.end() == len(segment):
            return True

        suffix = segment[match.end() :]
        if suffix.startswith(_ENTITY_SUFFIXES):
            return True
        next_character = suffix[0]
        separated_by_whitespace = False
        if next_character in "\r\n":
            return True
        if next_character.isspace():
            separated_by_whitespace = True
            whitespace_length = len(suffix) - len(suffix.lstrip())
            whitespace = suffix[:whitespace_length]
            remainder = suffix[whitespace_length:]
            if "\r" in whitespace or "\n" in whitespace or not remainder:
                return True
            if remainder.startswith(_ENTITY_SUFFIXES):
                return True
            next_character = remainder[0]
        category = unicodedata.category(next_character)
        return (
            category.startswith(("P", "S"))
            and (
                separated_by_whitespace
                or next_character not in _ENTITY_CONTINUATION
            )
        )

    def replace_segment(segment: str) -> str:
        def replace(match: re.Match[str]) -> str:
            if not has_approved_boundary(match, segment):
                return match.group(0)
            entity = match.group("entity")
            normalized_literals.append(entity)
            return literal_tokens[entity]

        return entity_pattern.sub(replace, segment)

    pieces: list[str] = []
    previous_end = 0
    for match in _PLACEHOLDER.finditer(normalized_template):
        pieces.append(replace_segment(normalized_template[previous_end : match.start()]))
        pieces.append(match.group(0))
        previous_end = match.end()
    pieces.append(replace_segment(normalized_template[previous_end:]))
    return "".join(pieces), tuple(dict.fromkeys(normalized_literals))


def _mask_ranges(text: str, ranges: tuple[tuple[int, int], ...]) -> str:
    if not ranges:
        return text
    characters = list(text)
    for start, end in ranges:
        characters[start:end] = " " * (end - start)
    return "".join(characters)


def _classify_unmarked_product_references(
    text: str,
    evidence_product_names: tuple[str, ...],
) -> tuple[
    str,
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[tuple[str, ...], ...],
    tuple[str, ...],
]:
    spans: list[str] = []
    normalized_spans: list[str] = []
    classifications: list[str] = []
    evidence_sources: list[tuple[str, ...]] = []
    rejected_spans: list[str] = []
    approved_ranges: list[tuple[int, int]] = []

    for match in _UNMARKED_PRODUCT_REFERENCE.finditer(text):
        span = match.group(0)
        normalized_span = unicodedata.normalize("NFKC", span).strip()
        sources = tuple(
            name for name in evidence_product_names if normalized_span in name
        )
        if _GENERIC_PRODUCT_REFERENCE.fullmatch(normalized_span):
            classification = "GENERIC_PRODUCT_CLASS"
            approved_ranges.append(match.span())
        elif any(normalized_span != source for source in sources):
            classification = "EVIDENCE_NAME_DERIVED"
            approved_ranges.append(match.span())
        else:
            classification = "UNAPPROVED_PRODUCT_REFERENCE"
            rejected_spans.append(span)
        spans.append(span)
        normalized_spans.append(normalized_span)
        classifications.append(classification)
        evidence_sources.append(sources)

    return (
        _mask_ranges(text, tuple(approved_ranges)),
        tuple(spans),
        tuple(normalized_spans),
        tuple(classifications),
        tuple(evidence_sources),
        tuple(rejected_spans),
    )


def _mask_evidence_derived_index_references(
    text: str,
    evidence_product_names: tuple[str, ...],
) -> str:
    approved_ranges = tuple(
        match.span()
        for match in _EVIDENCE_DERIVED_INDEX_REFERENCE.finditer(text)
        if any(match.group(0) in name for name in evidence_product_names)
    )
    return _mask_ranges(text, approved_ranges)


def _canonical_number(value: object) -> str | None:
    candidate = unicodedata.normalize("NFKC", str(value)).strip().replace(",", "")
    if not candidate or re.fullmatch(r"[-+]?\d+(?:\.\d+)?", candidate) is None:
        return None
    try:
        number = Decimal(candidate)
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    normalized = format(number.normalize(), "f")
    return "0" if normalized in {"-0", "+0"} else normalized


@dataclass(frozen=True, slots=True)
class _NumberValidation:
    scrubbed: str
    spans: tuple[str, ...]
    normalized_spans: tuple[str, ...]
    classifications: tuple[str, ...]
    allowed_evidence_values: tuple[str, ...]
    allowed_derived_values: tuple[str, ...]
    contexts: tuple[NumberContext, ...]
    enumeration_candidate_sequence: tuple[str, ...]

    @property
    def rejected(self) -> bool:
        return "UNAPPROVED_NUMBER" in self.classifications


def _logical_line_ranges(text: str) -> tuple[tuple[int, int], ...]:
    ranges: list[tuple[int, int]] = []
    start = 0
    for separator in _LOGICAL_LINE_SEPARATOR.finditer(text):
        ranges.append((start, separator.start()))
        start = separator.end()
    ranges.append((start, len(text)))
    return tuple(ranges)


def _inline_enumeration_matches(text: str) -> tuple[re.Match[str], ...]:
    """Return only complete, structurally introduced inline list markers."""

    approved: list[re.Match[str]] = []
    for line_start, line_end in _logical_line_ranges(text):
        matches = tuple(_INLINE_LIST_ENUMERATION.finditer(text, line_start, line_end))
        if not matches or int(matches[0].group("number")) != 1:
            continue

        intro = text[line_start : matches[0].start()].rstrip()
        if intro and intro[-1] not in _INLINE_LIST_INTRO_TERMINATORS:
            continue

        item_ranges = tuple(
            (current.end(), following.start())
            for current, following in zip(matches, matches[1:], strict=False)
        ) + ((matches[-1].end(), line_end),)
        if any(not text[start:end].strip() for start, end in item_ranges):
            continue
        approved.extend(matches)
    return tuple(approved)


def _validate_numbers(
    text: str,
    generation_input: GenerationInput,
    placeholders: dict[str, EvidencePlaceholder],
) -> _NumberValidation:
    allowed_evidence_values = tuple(
        dict.fromkeys(
            normalized
            for placeholder in placeholders.values()
            if placeholder.role == "fact"
            if (normalized := _canonical_number(placeholder.value)) is not None
        )
    )
    result_row_count = len(
        {
            item.source_row_id
            for item in generation_input.evidence
            if item.source_row_id and item.product_key
        }
    )
    allowed_derived_values = tuple(
        str(index) for index in range(1, result_row_count + 1)
    )
    line_enumeration_matches = tuple(_LIST_ENUMERATION.finditer(text))
    inline_enumeration_matches = _inline_enumeration_matches(text)
    enumeration_matches = tuple(
        sorted(
            {
                match.span("number"): match
                for match in (
                    *line_enumeration_matches,
                    *inline_enumeration_matches,
                )
            }.values(),
            key=lambda match: match.start("number"),
        )
    )
    enumeration_values = tuple(
        int(match.group("number")) for match in enumeration_matches
    )
    enumeration_sequence_is_valid = (
        enumeration_values == tuple(range(1, result_row_count + 1))
        and result_row_count > 0
    )
    enumeration_candidate_spans = {
        match.span("number") for match in enumeration_matches
    }
    valid_enumeration_spans = (
        enumeration_candidate_spans
        if enumeration_sequence_is_valid
        else set()
    )
    logical_separators = tuple(_LOGICAL_LINE_SEPARATOR.finditer(text))

    spans: list[str] = []
    normalized_spans: list[str] = []
    classifications: list[str] = []
    approved_ranges: list[tuple[int, int]] = []
    contexts: list[NumberContext] = []
    for match in _NUMBER.finditer(text):
        span = match.group(0)
        normalized = _canonical_number(span)
        if match.span() in valid_enumeration_spans:
            classification = "LIST_ENUMERATION"
        elif (
            normalized == str(result_row_count)
            and result_row_count > 0
            and _RESULT_COUNT.match(text, match.end()) is not None
        ):
            classification = "RESULT_COUNT"
        elif normalized is not None and normalized in allowed_evidence_values:
            classification = "EVIDENCE_NUMERIC_VALUE"
        else:
            classification = "UNAPPROVED_NUMBER"
        if classification != "UNAPPROVED_NUMBER":
            approved_ranges.append(match.span())
        spans.append(span)
        normalized_spans.append(normalized or span)
        classifications.append(classification)

        preceding_separators = tuple(
            separator for separator in logical_separators if separator.end() <= match.start()
        )
        following_separator = next(
            (
                separator
                for separator in logical_separators
                if separator.start() >= match.end()
            ),
            None,
        )
        line_start = preceding_separators[-1].end() if preceding_separators else 0
        line_end = following_separator.start() if following_separator is not None else len(text)
        line_prefix = text[line_start : match.start()]
        is_list_candidate = match.span() in enumeration_candidate_spans
        if is_list_candidate:
            candidate_rejection_reason = (
                None
                if enumeration_sequence_is_valid
                else "SEQUENCE_NOT_EXACT_1_TO_RESULT_COUNT"
            )
        elif line_prefix.strip():
            candidate_rejection_reason = "NON_WHITESPACE_LINE_PREFIX"
        elif text[match.end() :].startswith((r"\.", r"\)")):
            candidate_rejection_reason = "ESCAPED_ENUMERATION_MARKER"
        elif text[match.end() :].startswith((".", ")")):
            candidate_rejection_reason = "LIST_PREFIX_PATTERN_MISMATCH"
        else:
            candidate_rejection_reason = "UNSUPPORTED_ENUMERATION_MARKER"
        contexts.append(
            NumberContext(
                span=span,
                start_index=match.start(),
                end_index=match.end(),
                structural_context=text[
                    max(0, match.start() - _NUMBER_CONTEXT_RADIUS) : min(
                        len(text), match.end() + _NUMBER_CONTEXT_RADIUS
                    )
                ],
                line_index=len(preceding_separators) + 1,
                line_prefix=line_prefix[-_NUMBER_CONTEXT_RADIUS:],
                line_length=line_end - line_start,
                is_list_candidate=is_list_candidate,
                candidate_rejection_reason=candidate_rejection_reason,
            )
        )

    return _NumberValidation(
        scrubbed=_mask_ranges(text, tuple(approved_ranges)),
        spans=tuple(spans),
        normalized_spans=tuple(normalized_spans),
        classifications=tuple(classifications),
        allowed_evidence_values=allowed_evidence_values,
        allowed_derived_values=allowed_derived_values,
        contexts=tuple(contexts),
        enumeration_candidate_sequence=tuple(str(value) for value in enumeration_values),
    )


class PostGenerationValidator:
    """Accept only status-preserving, placeholder-grounded model output."""

    def validate(
        self,
        generation_input: GenerationInput,
        prompt: EvidenceOnlyPrompt,
        raw_output: str,
    ) -> PostGenerationValidation:
        if not isinstance(raw_output, str) or not raw_output.strip():
            return PostGenerationValidation(GenerationValidationStatus.REJECTED_EMPTY)
        normalized_output, normalization_reason = _normalize_nonsemantic_wrapper(
            raw_output
        )
        try:
            payload = json.loads(normalized_output)
        except json.JSONDecodeError:
            return PostGenerationValidation(
                GenerationValidationStatus.REJECTED_FORMAT,
                reason=GenerationValidationReason.NON_JSON_OUTPUT,
            )
        if (
            not isinstance(payload, dict)
            or set(payload) != {"status", "answer"}
            or not isinstance(payload.get("status"), str)
            or not isinstance(payload.get("answer"), str)
        ):
            return PostGenerationValidation(
                GenerationValidationStatus.REJECTED_FORMAT,
                reason=GenerationValidationReason.INVALID_JSON_SHAPE,
            )
        if payload["status"] != generation_input.support_status.value:
            return PostGenerationValidation(GenerationValidationStatus.REJECTED_STATUS)

        template = payload["answer"].strip()
        if not template:
            return PostGenerationValidation(GenerationValidationStatus.REJECTED_EMPTY)
        if _RECOMMENDATION.search(template):
            return PostGenerationValidation(
                GenerationValidationStatus.REJECTED_RECOMMENDATION
            )

        placeholders = _placeholder_map(prompt)
        template, normalized_entity_literals = _normalize_evidence_entity_literals(
            template,
            placeholders,
        )
        product_reference_spans: tuple[str, ...] = ()
        product_reference_normalized_spans: tuple[str, ...] = ()
        product_reference_classifications: tuple[str, ...] = ()
        product_reference_evidence_sources: tuple[tuple[str, ...], ...] = ()
        number_validation = _NumberValidation("", (), (), (), (), (), (), ())
        marker_mismatches: tuple[MarkerMismatch, ...] = ()

        def reject(
            status: GenerationValidationStatus,
            reason: GenerationValidationReason | None = None,
            *,
            residual_entity_literals: tuple[str, ...] = (),
        ) -> PostGenerationValidation:
            return PostGenerationValidation(
                status,
                reason=reason,
                normalized_entity_literals=normalized_entity_literals,
                residual_entity_literals=residual_entity_literals,
                unmarked_product_reference_spans=product_reference_spans,
                unmarked_product_reference_normalized_spans=(
                    product_reference_normalized_spans
                ),
                unmarked_product_reference_classifications=(
                    product_reference_classifications
                ),
                unmarked_product_reference_evidence_sources=(
                    product_reference_evidence_sources
                ),
                unmarked_product_reference_rule=_UNMARKED_PRODUCT_REFERENCE_RULE,
                detected_number_spans=number_validation.spans,
                normalized_number_spans=number_validation.normalized_spans,
                number_classifications=number_validation.classifications,
                allowed_evidence_numeric_values=(
                    number_validation.allowed_evidence_values
                ),
                allowed_derived_numeric_values=(
                    number_validation.allowed_derived_values
                ),
                number_contexts=number_validation.contexts,
                enumeration_candidate_sequence=(
                    number_validation.enumeration_candidate_sequence
                ),
                number_rule=_NUMBER_RULE,
                marker_mismatches=marker_mismatches,
                marker_rule=_ENTITY_MARKER_RULE,
            )

        placeholder_candidates = tuple(_PLACEHOLDER_CANDIDATE.findall(template))
        if any(token not in placeholders for token in placeholder_candidates):
            return reject(
                GenerationValidationStatus.REJECTED_ENTITY,
                GenerationValidationReason.UNKNOWN_PLACEHOLDER,
            )
        used_tokens = tuple(_PLACEHOLDER.findall(template))
        if any(token not in placeholders for token in used_tokens):
            return reject(
                GenerationValidationStatus.REJECTED_ENTITY,
                GenerationValidationReason.UNKNOWN_PLACEHOLDER,
            )
        marker_mismatches = _marker_mismatches(template, placeholders)
        if marker_mismatches:
            return reject(
                GenerationValidationStatus.REJECTED_ENTITY,
                GenerationValidationReason.ENTITY_MARKER_ROLE_MISMATCH,
            )
        scrubbed = _PLACEHOLDER.sub("", template)

        entity_values = tuple(
            dict.fromkeys(
                unicodedata.normalize("NFKC", placeholder.value).strip()
                for placeholder in placeholders.values()
                if placeholder.role in {"product_name", "product_identifier"}
            )
        )
        evidence_product_names = tuple(
            dict.fromkeys(
                unicodedata.normalize("NFKC", placeholder.value).strip()
                for placeholder in placeholders.values()
                if placeholder.role == "product_name"
            )
        )
        (
            scrubbed,
            product_reference_spans,
            product_reference_normalized_spans,
            product_reference_classifications,
            product_reference_evidence_sources,
            rejected_product_reference_spans,
        ) = _classify_unmarked_product_references(scrubbed, evidence_product_names)
        scrubbed = _mask_evidence_derived_index_references(
            scrubbed,
            evidence_product_names,
        )
        if rejected_product_reference_spans:
            return reject(
                GenerationValidationStatus.REJECTED_ENTITY,
                GenerationValidationReason.UNMARKED_PRODUCT_REFERENCE,
            )
        if _IDENTIFIER.search(scrubbed):
            return reject(
                GenerationValidationStatus.REJECTED_ENTITY,
                GenerationValidationReason.UNMARKED_IDENTIFIER,
            )
        unknown_uppercase_references = tuple(
            match.group(0)
            for match in _UPPERCASE_REFERENCE.finditer(scrubbed)
            if match.group(0) not in _GENERIC_UPPERCASE_REFERENCES
            and not any(match.group(0) in name for name in evidence_product_names)
        )
        if unknown_uppercase_references:
            return reject(
                GenerationValidationStatus.REJECTED_ENTITY,
                GenerationValidationReason.UNMARKED_IDENTIFIER,
            )
        residual_entity_literals = tuple(
            value for value in entity_values if value and value in scrubbed
        )
        if residual_entity_literals:
            return reject(
                GenerationValidationStatus.REJECTED_ENTITY,
                GenerationValidationReason.LITERAL_EVIDENCE_ENTITY,
                residual_entity_literals=residual_entity_literals,
            )
        number_validation = _validate_numbers(scrubbed, generation_input, placeholders)
        scrubbed = number_validation.scrubbed
        if number_validation.rejected:
            return reject(GenerationValidationStatus.REJECTED_NUMBER)
        if _UNSUPPORTED_FINANCIAL_CLAIM.search(scrubbed):
            return reject(
                GenerationValidationStatus.REJECTED_ENTITY,
                GenerationValidationReason.UNSUPPORTED_FINANCIAL_CLAIM,
            )

        allowed_units = {
            item.unit for item in generation_input.evidence if item.unit is not None
        }
        units = set(_FINANCIAL_UNIT.findall(scrubbed))
        if units - allowed_units:
            return reject(GenerationValidationStatus.REJECTED_UNIT)

        if (
            generation_input.support_status.value in {"SUPPORTED", "PARTIAL"}
            and (
                generation_input.evidence
                or generation_input.aggregate_evidence
            )
            and not used_tokens
        ):
            return reject(
                GenerationValidationStatus.REJECTED_FORMAT,
                GenerationValidationReason.MISSING_EVIDENCE_PLACEHOLDER,
            )

        if generation_input.support_status.value in {"UNSUPPORTED", "NO_MATCH"}:
            if used_tokens or _NAME_MARKER.search(template) or _IDENTIFIER_MARKER.search(template):
                return reject(
                    GenerationValidationStatus.REJECTED_ENTITY,
                    GenerationValidationReason.ENTITY_IN_UNSUPPORTED_RESPONSE,
                )

        answer = template
        for token in used_tokens:
            answer = answer.replace(token, placeholders[token].value)
        if _PLACEHOLDER_CANDIDATE.search(answer):
            return reject(
                GenerationValidationStatus.REJECTED_ENTITY,
                GenerationValidationReason.UNKNOWN_PLACEHOLDER,
            )
        if not answer or len(answer) > 1000:
            return reject(
                GenerationValidationStatus.REJECTED_FORMAT,
                GenerationValidationReason.ANSWER_LENGTH_INVALID,
            )
        return PostGenerationValidation(
            GenerationValidationStatus.ACCEPTED,
            answer=answer,
            reason=(
                GenerationValidationReason.EVIDENCE_LITERAL_NORMALIZED
                if normalized_entity_literals
                else normalization_reason
            ),
            normalized_entity_literals=normalized_entity_literals,
            unmarked_product_reference_spans=product_reference_spans,
            unmarked_product_reference_normalized_spans=(
                product_reference_normalized_spans
            ),
            unmarked_product_reference_classifications=(
                product_reference_classifications
            ),
            unmarked_product_reference_evidence_sources=(
                product_reference_evidence_sources
            ),
            unmarked_product_reference_rule=_UNMARKED_PRODUCT_REFERENCE_RULE,
            detected_number_spans=number_validation.spans,
            normalized_number_spans=number_validation.normalized_spans,
            number_classifications=number_validation.classifications,
            allowed_evidence_numeric_values=number_validation.allowed_evidence_values,
            allowed_derived_numeric_values=number_validation.allowed_derived_values,
            number_contexts=number_validation.contexts,
            enumeration_candidate_sequence=(
                number_validation.enumeration_candidate_sequence
            ),
            number_rule=_NUMBER_RULE,
            marker_mismatches=marker_mismatches,
            marker_rule=_ENTITY_MARKER_RULE,
        )


__all__ = [
    "MarkerMismatch",
    "NumberContext",
    "PostGenerationValidation",
    "PostGenerationValidator",
]
