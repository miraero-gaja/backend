"""Parse submission Turtle and detect drift from Python semantic registries."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from mappings.aliases.registry import _FIELD_ALIASES, _PRODUCT_ALIASES
from mappings.core import CORE_FIELD_MAPPINGS
from mappings.semantic import SEMANTIC_FIELD_APPROVALS, ClaimStatus, OperationStatus

ROOT = Path(__file__).resolve().parents[2]
ONTOLOGY = ROOT / "ontology"
FILES = ("common.ttl", "bond_kr.ttl", "etf_kr.ttl", "etf_gl.ttl", "fund_pub.ttl")
TABLES = {
    "bond_kr.ttl": "PRBD01N001",
    "etf_kr.ttl": "PREF01N001",
    "etf_gl.ttl": "PREF02N001",
    "fund_pub.ttl": "PRFD01N001",
}
MA = "urn:miraeasset:financial-agent:ontology:2026:"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


@dataclass(frozen=True, slots=True)
class Literal:
    value: str


Node = str | Literal
Triple = tuple[str, str, Node]


@dataclass(frozen=True, slots=True)
class Graph:
    prefixes: dict[str, str]
    triples: tuple[Triple, ...]

    def objects(self, subject: str, predicate: str) -> tuple[Node, ...]:
        return tuple(o for s, p, o in self.triples if s == subject and p == predicate)

    def subjects(self, predicate: str, obj: Node) -> tuple[str, ...]:
        return tuple(s for s, p, o in self.triples if p == predicate and o == obj)


@dataclass(frozen=True, slots=True)
class Token:
    kind: str
    value: str
    offset: int


TOKEN = re.compile(
    r"(?P<SPACE>\s+)|(?P<COMMENT>\#[^\r\n]*)|(?P<PREFIX>@prefix)"
    r"|(?P<IRI><[^<>\s]+>)|(?P<STRING>\"(?:\\.|[^\"\\])*\")"
    r"|(?P<QNAME>[A-Za-z_][A-Za-z0-9_-]*:(?:[A-Za-z_][A-Za-z0-9_.-]*)?)"
    r"|(?P<A>a)(?=\s)|(?P<PUNCT>[;,.])"
)


def tokenize(text: str) -> tuple[Token, ...]:
    result: list[Token] = []
    offset = 0
    while offset < len(text):
        match = TOKEN.match(text, offset)
        if match is None:
            excerpt = text[offset : offset + 30].replace("\n", "\\n")
            raise ValueError(f"invalid Turtle token at {offset}: {excerpt!r}")
        kind = match.lastgroup
        assert kind is not None
        if kind not in {"SPACE", "COMMENT"}:
            result.append(Token(kind, match.group(), offset))
        offset = match.end()
    return tuple(result)


class TurtleParser:
    """Whole-document parser for the conservative Turtle subset used here."""

    def __init__(self, text: str) -> None:
        self.tokens = tokenize(text)
        self.index = 0
        self.prefixes: dict[str, str] = {}
        self.triples: list[Triple] = []

    def peek(self) -> Token | None:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def take(self, kind: str, value: str | None = None) -> Token:
        token = self.peek()
        if token is None or token.kind != kind or (value is not None and token.value != value):
            got = "EOF" if token is None else f"{token.kind} {token.value!r}"
            raise ValueError(f"expected {kind} {value or ''}, got {got}")
        self.index += 1
        return token

    def resource(self) -> str:
        token = self.peek()
        if token is None:
            raise ValueError("expected resource, got EOF")
        if token.kind == "IRI":
            self.index += 1
            return token.value[1:-1]
        if token.kind != "QNAME":
            raise ValueError(f"expected resource at {token.offset}")
        self.index += 1
        prefix, local = token.value.split(":", 1)
        if prefix not in self.prefixes or not local:
            raise ValueError(f"invalid or undefined QName: {token.value}")
        return self.prefixes[prefix] + local

    def predicate(self) -> str:
        if self.peek() is not None and self.peek().kind == "A":
            self.index += 1
            return RDF_TYPE
        return self.resource()

    def obj(self) -> Node:
        if self.peek() is not None and self.peek().kind == "STRING":
            return Literal(json.loads(self.take("STRING").value))
        return self.resource()

    def prefix(self) -> None:
        self.take("PREFIX")
        name = self.take("QNAME").value
        prefix, local = name.split(":", 1)
        if local or prefix in self.prefixes:
            raise ValueError(f"invalid or duplicate prefix: {name}")
        self.prefixes[prefix] = self.take("IRI").value[1:-1]
        self.take("PUNCT", ".")

    def statement(self) -> None:
        subject = self.resource()
        while True:
            predicate = self.predicate()
            while True:
                self.triples.append((subject, predicate, self.obj()))
                if self.peek() is None or self.peek().value != ",":
                    break
                self.take("PUNCT", ",")
            if self.peek() is None:
                raise ValueError("Turtle statement is missing its terminating dot")
            if self.peek().value == ".":
                self.take("PUNCT", ".")
                return
            self.take("PUNCT", ";")

    def parse(self) -> Graph:
        while self.peek() is not None and self.peek().kind == "PREFIX":
            self.prefix()
        if not self.prefixes:
            raise ValueError("Turtle document must declare prefixes")
        while self.peek() is not None:
            self.statement()
        return Graph(dict(self.prefixes), tuple(self.triples))


def parse(name: str) -> Graph:
    return TurtleParser((ONTOLOGY / name).read_text(encoding="utf-8")).parse()


def domain_graphs() -> dict[str, Graph]:
    return {name: parse(name) for name in TABLES}


def one_literal(graph: Graph, subject: str, prop: str) -> str:
    values = graph.objects(subject, MA + prop)
    assert len(values) == 1 and isinstance(values[0], Literal)
    return values[0].value


def one_resource(graph: Graph, subject: str, prop: str) -> str:
    values = graph.objects(subject, MA + prop)
    assert len(values) == 1 and isinstance(values[0], str)
    return values[0]


def local_set(graph: Graph, subject: str, prop: str) -> set[str]:
    values = graph.objects(subject, MA + prop)
    assert all(isinstance(value, str) and value.startswith(MA) for value in values)
    return {value.removeprefix(MA) for value in values if isinstance(value, str)}


def literal_set(graph: Graph, subject: str, prop: str) -> set[str]:
    values = graph.objects(subject, MA + prop)
    assert all(isinstance(value, Literal) for value in values)
    return {value.value for value in values if isinstance(value, Literal)}


def fields(graphs: dict[str, Graph]) -> dict[str, tuple[Graph, str]]:
    result: dict[str, tuple[Graph, str]] = {}
    for graph in graphs.values():
        for subject in graph.subjects(RDF_TYPE, MA + "SemanticField"):
            key = one_literal(graph, subject, "semanticKey")
            assert key not in result
            result[key] = (graph, subject)
    return result


def assert_registry_consistency(graphs: dict[str, Graph]) -> None:
    indexed = fields(graphs)
    expected = {m.semantic_field_key for m in CORE_FIELD_MAPPINGS} | {
        a.semantic_key for a in SEMANTIC_FIELD_APPROVALS
    }
    assert set(indexed) == expected
    for mapping in CORE_FIELD_MAPPINGS:
        graph, subject = indexed[mapping.semantic_field_key]
        assert one_literal(graph, subject, "logicalTableId") == mapping.logical_table_id
        assert one_literal(graph, subject, "sourceColumn") == mapping.source_column
        assert one_resource(graph, subject, "conceptStatus") == MA + mapping.semantic_status.value
        assert one_resource(graph, subject, "unitStatus") == MA + mapping.unit_status.value
        assert local_set(graph, subject, "allowedOperation") == set(mapping.allowed_operations)
        policy = mapping.null_equivalent_policy
        assert literal_set(graph, subject, "nullEquivalentLiteral") == (
            set(policy.literals) if policy is not None else set()
        )
        if policy is None:
            assert not graph.objects(
                subject, MA + "sourceLiteralClassification"
            )
            assert not graph.objects(
                subject, MA + "semanticLiteralClassification"
            )
        else:
            assert one_resource(
                graph, subject, "sourceLiteralClassification"
            ) == MA + policy.source_classification
            assert one_resource(
                graph, subject, "semanticLiteralClassification"
            ) == MA + policy.semantic_classification
        if mapping.semantic_status.value != "CONFIRMED":
            assert not graph.objects(subject, MA + "allowedOperation")
    for approval in SEMANTIC_FIELD_APPROVALS:
        graph, subject = indexed[approval.semantic_key]
        assert one_literal(graph, subject, "logicalTableId") == approval.logical_table_id
        assert one_literal(graph, subject, "sourceColumn") == approval.source_column
        assert one_resource(graph, subject, "conceptStatus") == MA + approval.concept.status.value
        assert one_resource(graph, subject, "unitStatus") == MA + approval.unit.status.value
        assert one_resource(graph, subject, "valueDomainStatus") == MA + approval.value_domain.status.value
        assert local_set(graph, subject, "allowedOperation") == set(approval.open_operations)
        closed = {o.operation for o in approval.operations if o.status is OperationStatus.CLOSED}
        assert local_set(graph, subject, "closedOperation") == closed
        if approval.concept.status is ClaimStatus.UNKNOWN:
            assert not graph.objects(subject, MA + "allowedOperation")
        claims = (approval.concept, approval.unit, approval.value_domain)
        provenance = (
            *(item for claim in claims for item in claim.provenance),
            *(item for operation in approval.operations for item in operation.provenance),
        )
        expected_tiers = {
            claim.evidence_tier.value
            for claim in claims
            if claim.evidence_tier is not None
        } | {item.evidence_tier.value for item in provenance}
        assert local_set(graph, subject, "evidenceTier") == expected_tiers
        ontology_provenance = {
            value.value
            for value in graph.objects(subject, MA + "provenance")
            if isinstance(value, Literal)
        }
        assert {
            item.artifact_relative_path
            for item in provenance
            if item.artifact_relative_path
        } <= ontology_provenance
        expected_identities = {
            f"sha256:{item.source_identity}" for item in provenance
        }
        observed_identities = {
            value.value
            for value in graph.objects(subject, MA + "sourceIdentity")
            if isinstance(value, Literal)
        }
        assert observed_identities == expected_identities


def test_required_five_turtle_files_exist_and_parse_completely() -> None:
    assert {path.name for path in ONTOLOGY.glob("*.ttl")} == set(FILES)
    assert all(parse(name).triples for name in FILES)


def test_parser_rejects_invalid_turtle_syntax() -> None:
    with pytest.raises(ValueError, match="terminating dot"):
        TurtleParser("@prefix ma: <urn:test:> . ma:x a ma:y").parse()


def test_namespace_and_domain_logical_tables_are_consistent() -> None:
    graphs = {name: parse(name) for name in FILES}
    assert {graph.prefixes["ma"] for graph in graphs.values()} == {MA}
    for name, table in TABLES.items():
        graph = graphs[name]
        contracts = graph.subjects(RDF_TYPE, MA + "DomainOntology")
        assert len(contracts) == 1
        assert one_literal(graph, contracts[0], "logicalTableId") == table
        assert graph.objects(contracts[0], MA + "sourceSnapshot") == (MA + "Snapshot20260824",)


def test_g2_and_g3_registry_coverage_and_operations_do_not_drift() -> None:
    assert_registry_consistency(domain_graphs())


def test_operation_drift_detector_rejects_extra_open_permission() -> None:
    graphs = domain_graphs()
    graph, subject = fields(graphs)["pref02.aum_latest"]
    graphs["etf_gl.ttl"] = Graph(
        graph.prefixes,
        (*graph.triples, (subject, MA + "allowedOperation", MA + "GT")),
    )
    with pytest.raises(AssertionError):
        assert_registry_consistency(graphs)


def test_pref02_base_index_null_equivalent_policy_does_not_drift() -> None:
    graphs = domain_graphs()
    graph, subject = fields(graphs)["pref02.base_index_name"]

    assert literal_set(graph, subject, "nullEquivalentLiteral") == {
        "Index is not provided by Management Company",
        "Index is not available on Lipper Database",
    }
    assert one_resource(
        graph, subject, "sourceLiteralClassification"
    ) == MA + "SOURCE_NOT_AVAILABLE"
    assert one_resource(
        graph, subject, "semanticLiteralClassification"
    ) == MA + "NULL_EQUIVALENT"

    graphs["etf_gl.ttl"] = Graph(
        graph.prefixes,
        (
            *graph.triples,
            (
                subject,
                MA + "nullEquivalentLiteral",
                Literal("invented generic sentinel"),
            ),
        ),
    )
    with pytest.raises(AssertionError):
        assert_registry_consistency(graphs)


def test_null_equivalent_ontology_vocabulary_is_explicit() -> None:
    common = parse("common.ttl")
    rdf_property = "http://www.w3.org/1999/02/22-rdf-syntax-ns#Property"

    for classification in ("SOURCE_NOT_AVAILABLE", "NULL_EQUIVALENT"):
        assert common.objects(
            MA + classification, RDF_TYPE
        ) == (MA + "LiteralClassification",)
    for predicate in (
        "nullEquivalentLiteral",
        "sourceLiteralClassification",
        "semanticLiteralClassification",
    ):
        assert common.objects(MA + predicate, RDF_TYPE) == (rdf_property,)


def test_aliases_match_explicit_registry_without_approving_operations() -> None:
    graphs = domain_graphs()
    indexed = fields(graphs)
    expected_fields: dict[str, set[str]] = {}
    for alias in _FIELD_ALIASES:
        for key in alias.semantic_keys:
            expected_fields.setdefault(key, set()).add(alias.alias)
    observed_fields: dict[str, set[str]] = {}
    for key, (graph, subject) in indexed.items():
        aliases = {
            value.value
            for value in graph.objects(subject, MA + "alias")
            if isinstance(value, Literal)
        }
        if aliases:
            observed_fields[key] = aliases
    assert set(observed_fields) == set(expected_fields)
    for key, expected in expected_fields.items():
        graph, subject = indexed[key]
        observed = {v.value for v in graph.objects(subject, MA + "alias") if isinstance(v, Literal)}
        assert observed == expected
    products: dict[str, set[str]] = {}
    for alias in _PRODUCT_ALIASES:
        products.setdefault(alias.logical_table_id, set()).add(alias.alias)
    for name, table in TABLES.items():
        graph = graphs[name]
        contract = graph.subjects(RDF_TYPE, MA + "DomainOntology")[0]
        assert literal_set(graph, contract, "alias") == products[table]


def test_pref02_aum_and_expense_ratio_remain_fail_closed() -> None:
    graph = domain_graphs()["etf_gl.ttl"]
    indexed = fields({"etf_gl.ttl": graph})
    aum = indexed["pref02.aum_latest"][1]
    assert local_set(graph, aum, "allowedOperation") == {"PROJECT", "SORT_DESC"}
    assert local_set(graph, aum, "closedOperation") == {"LT", "LE", "GT", "GE"}
    assert one_resource(graph, aum, "unitStatus") == MA + "NEED_REVIEW"
    assert not graph.objects(aum, MA + "unit")
    expense = indexed["pref02.expense_ratio"][1]
    assert not graph.objects(expense, MA + "allowedOperation")
    assert local_set(graph, expense, "closedOperation") == {
        "EQ", "NE", "LT", "LE", "GT", "GE", "SORT_ASC", "SORT_DESC"
    }


def test_pref02_four_concepts_are_t1_official_schema_confirmed() -> None:
    """All four PREF02 G3 fields are concept-CONFIRMED directly from the
    20260824 official schema (T1), matching the current semantic registry.
    """

    graph = domain_graphs()["etf_gl.ttl"]
    indexed = fields({"etf_gl.ttl": graph})
    for semantic_key in (
        "pref02.expense_ratio",
        "pref02.aum_latest",
        "pref02.product_identifier",
        "pref02.product_name",
    ):
        subject = indexed[semantic_key][1]
        assert one_resource(graph, subject, "conceptStatus") == MA + "CONFIRMED"
        assert "T1_OFFICIAL_SCHEMA" in local_set(graph, subject, "evidenceTier")


def test_pref02_product_identifier_has_no_official_pk_claim() -> None:
    graph = domain_graphs()["etf_gl.ttl"]
    subject = fields({"etf_gl.ttl": graph})["pref02.product_identifier"][1]
    rationale = one_literal(graph, subject, "rationale").lower()
    assert "official primary key" not in rationale or (
        "not a declared official primary key" in rationale
    )
    assert "statistical unique candidate" in rationale


def test_prbd_four_fields_are_t1_confirmed_with_operations_still_closed() -> None:
    """PRBD concept is now T1-confirmed from the official 20260824 schema,
    but unit, scale, and code-value meaning remain unapproved, so no
    operation is OPEN.
    """

    graph = domain_graphs()["bond_kr.ttl"]
    indexed = fields({"bond_kr.ttl": graph})
    unresolved_keys = {
        "prbd.pd_risk_gcd_unresolved", "prbd.dur_unresolved",
        "prbd.ndy_dur_unresolved", "prbd.cov_unresolved",
    }
    assert unresolved_keys < set(indexed)
    for key in unresolved_keys:
        _, subject = indexed[key]
        assert one_resource(graph, subject, "conceptStatus") == MA + "CONFIRMED"
        assert "T1_OFFICIAL_SCHEMA" in local_set(graph, subject, "evidenceTier")
        assert one_resource(graph, subject, "unitStatus") == MA + "NEED_REVIEW"
        assert one_resource(graph, subject, "valueDomainStatus") == MA + "NEED_REVIEW"
        assert not graph.objects(subject, MA + "allowedOperation")
        assert local_set(graph, subject, "closedOperation") == {
            "EQ", "NE", "LT", "LE", "GT", "GE", "SORT_ASC", "SORT_DESC"
        }


def test_prbd_source_columns_use_lowercase_current_physical_identity() -> None:
    graph = domain_graphs()["bond_kr.ttl"]
    indexed = fields({"bond_kr.ttl": graph})
    observed = {
        key: one_literal(field_graph, subject, "sourceColumn")
        for key, (field_graph, subject) in indexed.items()
    }
    assert {
        key: observed[key]
        for key in (
            "prbd.pd_risk_gcd_unresolved",
            "prbd.dur_unresolved",
            "prbd.ndy_dur_unresolved",
            "prbd.cov_unresolved",
        )
    } == {
        "prbd.pd_risk_gcd_unresolved": "pd_risk_gcd",
        "prbd.dur_unresolved": "dur",
        "prbd.ndy_dur_unresolved": "ndy_dur",
        "prbd.cov_unresolved": "cov",
    }
    for value in observed.values():
        assert value == value.lower()


def test_prbd_pd_risk_gcd_carries_no_code_meaning_or_ordinal_direction() -> None:
    """The ontology may record that pd_risk_gcd is T1-confirmed as a coded
    text field, but it must not encode what any raw code value means, its
    ordering, or its risk direction anywhere in the triples or vocabulary.
    """

    graph = domain_graphs()["bond_kr.ttl"]
    subject = fields({"bond_kr.ttl": graph})["prbd.pd_risk_gcd_unresolved"][1]

    forbidden_predicate_terms = (
        "codemeaning", "ordinal", "direction", "riskorder", "coderank", "codevalue",
    )
    predicates = {p for s, p, o in graph.triples if s == subject}
    for predicate in predicates:
        local_name = predicate.removeprefix(MA).lower()
        assert not any(term in local_name for term in forbidden_predicate_terms)

    rationale = one_literal(graph, subject, "rationale").lower()
    forbidden_meaning_terms = (
        "high risk", "low risk", "safest", "riskiest", "ascending", "descending",
    )
    assert not any(term in rationale for term in forbidden_meaning_terms)


def test_pref02_exchange_codes_have_no_invented_semantic_key() -> None:
    graph = domain_graphs()["etf_gl.ttl"]
    subjects = graph.subjects(RDF_TYPE, MA + "UnresolvedSourceField")
    exchange = [s for s in subjects if one_literal(graph, s, "sourceColumn") == "pd_exg_mkt_cd"]
    assert len(exchange) == 1
    assert not graph.objects(exchange[0], MA + "semanticKey")
    assert not graph.objects(exchange[0], MA + "allowedOperation")
    assert one_resource(graph, exchange[0], "conceptStatus") == MA + "UNKNOWN"


def test_all_five_domains_use_20260824_snapshot_and_provenance() -> None:
    snapshot = MA + "Snapshot20260824"
    assert parse("common.ttl").objects(snapshot, MA + "snapshotDate") == (
        Literal("2026-08-24"),
    )
    for name in FILES:
        graph = parse(name)
        for contract in graph.subjects(RDF_TYPE, MA + "DomainOntology"):
            assert graph.objects(contract, MA + "sourceSnapshot") == (snapshot,)
        subjects = graph.subjects(RDF_TYPE, MA + "SemanticField")
        if subjects:
            assert all(
                graph.objects(s, MA + "sourceSnapshot") == (snapshot,) for s in subjects
            )


def test_no_stale_20260711_or_g3a1_provenance_remains_in_ontology() -> None:
    stale_markers = ("Snapshot20260711", "2026-07-11", "g3a1_pref02", "g3a1_prbd")
    for name in FILES:
        text = (ONTOLOGY / name).read_text(encoding="utf-8")
        for marker in stale_markers:
            assert marker not in text, f"{marker!r} still present in {name}"
