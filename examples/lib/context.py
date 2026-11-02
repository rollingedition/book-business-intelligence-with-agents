"""Layered context: what the agent is given beyond the question, built in layers and fitted to a token budget.

Four layers, each a list of items:
- `schema`: every table and column, as `describe_schema()` lists them. Always one item, and always kept.
- `columns`: notes on tables and columns whose names mislead (`data/shop/columns.toml`), one item per note.
- `glossary`: what the shop's business words mean in terms of its tables (`data/shop/glossary.toml`).
- `verified`: verified queries, each a question and SQL a person checked (`data/shop/verified_queries.toml`).
  Only the few most similar to the question are retrieved, by `QueryIndex`.

`build_context()` picks the layers asked for, keeps items in that priority order until the token budget is spent,
and renders what it kept with the stable layers first and the retrieved queries last, so the question, which the
prompt puts after the context, sits next to the examples most like it. Tokens are estimated from characters
(`estimate_tokens()`), not counted by the model's tokenizer, which the examples don't load.
"""
from __future__ import annotations

import math
import re
import tomllib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from .warehouse import describe_schema

SHOP = Path(__file__).resolve().parent.parent / "data" / "shop"
LAYERS = ("schema", "columns", "glossary", "verified")
HEADINGS = {
    "schema": "The warehouse:",
    "columns": "Notes on tables and columns:",
    "glossary": "What the shop's business terms mean:",
    "verified": "Verified queries for similar questions (checked by the shop's analysts; adapt them to the question):",
}
CHARS_PER_TOKEN = 3.5     # meant to overestimate tokens: on the prompt checked in chapter 4, the tokenizer averaged about 4.3


@dataclass(frozen=True)
class VerifiedQuery:
    name: str
    question: str
    sql: str
    role: str
    verified_at: str
    verified_by: str          # a team, never a person

    def show(self) -> str:
        return f"Question: {self.question}\n```sql\n{self.sql.strip()}\n```"


def load_column_notes(path: Path = SHOP / "columns.toml") -> list[str]:
    """Each table note and column note as one line, such as `analytics.fct_orders.placed_at: When ... in UTC.`"""
    with open(path, "rb") as f:
        tables = tomllib.load(f)["tables"]
    lines = []
    for table, entry in tables.items():
        lines.append(f"{table}: {entry['note']}")
        lines += [f"{table}.{column}: {note}" for column, note in entry.get("columns", {}).items()]
    return lines


def load_glossary(path: Path = SHOP / "glossary.toml") -> list[str]:
    """Each glossary entry as one line, `term: meaning`."""
    with open(path, "rb") as f:
        return [f"{t['term']}: {t['meaning']}" for t in tomllib.load(f)["terms"]]


def load_verified_queries(path: Path = SHOP / "verified_queries.toml") -> list[VerifiedQuery]:
    with open(path, "rb") as f:
        return [VerifiedQuery(**q) for q in tomllib.load(f)["queries"]]


# Retrieval. Words that name a value, not a kind of question, are masked first, so "March 2026" and "January 2025"
# look alike: a cheap lexical stand-in for masking the question's domain words before comparing.
MONTHS = ("january february march april may june july august september october november december "
          "jan feb mar apr jun jul aug sep sept oct nov dec").split()
REGIONS = ("emea", "amer", "apac")
STOPWORDS = set("a an the of in on for to by and or was were is are did do does what which how many much our we "
                "each per from with that this it its their there".split())


def question_terms(question: str) -> list[str]:
    """The question's words, lower-cased, with stopwords dropped and numbers, months and regions masked."""
    terms = []
    for word in re.findall(r"[a-z0-9_]+", question.lower()):
        if word in STOPWORDS:
            continue
        terms.append("<number>" if word.isdigit() else "<month>" if word in MONTHS
                     else "<region>" if word in REGIONS else word)
    return terms


class QueryIndex:
    """TF-IDF over the verified queries' masked questions; `search()` ranks them by cosine similarity."""

    def __init__(self, queries: list[VerifiedQuery]):
        self.queries = queries
        documents = [Counter(question_terms(q.question)) for q in queries]
        frequency = Counter(term for d in documents for term in d)
        self.idf = {t: math.log((1 + len(queries)) / (1 + n)) + 1 for t, n in frequency.items()}
        self.vectors = [self._vector(d) for d in documents]

    def _vector(self, counts: Counter) -> dict[str, float]:
        vector = {t: n * self.idf.get(t, 0.0) for t, n in counts.items()}
        norm = math.sqrt(sum(v * v for v in vector.values())) or 1.0
        return {t: v / norm for t, v in vector.items()}

    def search(self, question: str, k: int = 3, min_score: float = 0.4) -> list[tuple[float, VerifiedQuery]]:
        """The `k` most similar verified queries scoring at least `min_score`, best first."""
        target = self._vector(Counter(question_terms(question)))
        scored = [(round(sum(w * vector.get(t, 0.0) for t, w in target.items()), 3), query)
                  for vector, query in zip(self.vectors, self.queries)]
        scored.sort(key=lambda pair: (-pair[0], pair[1].name))
        return [(score, query) for score, query in scored[:k] if score >= min_score]


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


@dataclass
class Context:
    """The layers kept, in render order, each as its list of items; and what the budget left out."""
    items: dict[str, list[str]] = field(default_factory=dict)
    dropped: list[tuple[str, str]] = field(default_factory=list)    # (layer, the item's first line)

    @property
    def text(self) -> str:
        return "\n\n".join(HEADINGS[layer] + "\n" + ("\n\n" if layer == "verified" else "\n").join(items)
                           for layer, items in self.items.items() if items)

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)

    def layer_tokens(self) -> dict[str, int]:
        return {layer: estimate_tokens(Context({layer: items}).text) for layer, items in self.items.items() if items}


def layer_items(con: duckdb.DuckDBPyConnection, question: str, layer: str, k: int = 3) -> list[str]:
    if layer == "schema":
        return [describe_schema(con)]
    if layer == "columns":
        return load_column_notes()
    if layer == "glossary":
        return load_glossary()
    if layer == "verified":
        return [query.show() for _, query in QueryIndex(load_verified_queries()).search(question, k=k)]
    raise ValueError(f"unknown layer {layer!r}; layers: {', '.join(LAYERS)}")


def build_context(con: duckdb.DuckDBPyConnection, question: str, layers: tuple[str, ...] = LAYERS,
                  budget: int | None = None, k: int = 3) -> Context:
    """The context for one question: the layers named, in `LAYERS` order, fitted to `budget` tokens if given.

    Items are added layer by layer in the order of `layers`, which is their priority. An item that would take the
    context over the budget is dropped, and later, smaller items may still fit. The schema is never dropped.
    """
    chosen = {layer: [] for layer in LAYERS if layer in layers}
    context = Context(chosen)
    for layer in layers:
        for item in layer_items(con, question, layer, k):
            chosen[layer].append(item)
            if budget is not None and layer != "schema" and context.tokens > budget:
                chosen[layer].pop()
                context.dropped.append((layer, item.splitlines()[0]))
    return context


# The layer sets chapter 4 measures, each adding one layer to the last.
LAYER_SETS = (("schema",), ("schema", "columns"), ("schema", "columns", "glossary"), LAYERS)


def layer_set_name(layers: tuple[str, ...]) -> str:
    return "+".join(layers)


def grade_with_context(con: duckdb.DuckDBPyConnection, model, question, layers: tuple[str, ...],
                       budget: int | None = None) -> str:
    """Ask `model` for SQL with this context, run it, and grade it against the golden result: one outcome."""
    from .golden import golden_result, grade
    from .prompts import layered_sql_messages
    from .tools import extract_sql, run_sql

    context = build_context(con, question.question, layers, budget)
    reply = model.complete(layered_sql_messages(context.text, question.question))
    try:
        return grade(question, run_sql(con, extract_sql(reply)), golden_result(con, question))
    except duckdb.Error:
        return "error"
