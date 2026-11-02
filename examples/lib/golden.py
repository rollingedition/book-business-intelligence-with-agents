"""Golden questions: questions with a verified answer, the role that asks them and the kind of answer expected.

A golden question's `kind` is `answer` (the warehouse can answer it, and `golden_sql` returns the golden result),
`decline` (it can't, because the question is ambiguous or the data doesn't hold the answer, and the right answer
says so) or `forbidden` (the role asking may not see the answer, and the right answer declines). Results are
compared, not SQL text: `results_match()` accepts an answer when it has as many rows as the golden result and its
columns include every golden column, in any column order, with extra columns allowed (such as the year a question
named), in any row order unless the question says order matters, and with numbers equal within a relative tolerance
plus an absolute slack of half a unit in the last place the gold rounds to: half a cent for money (the default), and
0.00005 for a ratio the gold rounds to four places, so a near-miss rate doesn't match.
`grade()` turns one answer into one outcome.
Chapter 3 adds the full set of 48, split into `dev` (for tuning) and `test` (held out); each question also names the
warehouse traps it tests, and some carry a `check_sql`, an independent query that must return the same result.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from itertools import permutations
from pathlib import Path

import duckdb

from .answers import Answer
from .prompts import schema_only_messages
from .tools import extract_sql, run_sql

QUESTIONS = Path(__file__).resolve().parent.parent / "data" / "golden" / "questions.toml"


@dataclass(frozen=True)
class GoldenQuestion:
    question_id: str
    question: str
    role: str
    kind: str                         # "answer", "decline" or "forbidden"
    split: str                        # "dev" or "test"
    golden_sql: str = ""
    order_matters: bool = False
    tolerance: float = 0.0005         # relative
    absolute: float = 0.005           # half a unit in the gold's last rounded place: a cent for money
    note: str = ""
    decline_type: str = ""            # for a decline: "ambiguous" or "unanswerable"
    region: str = ""                  # for a regional_lead: the region they lead
    traps: tuple[str, ...] = ()       # the warehouse's traps the question tests
    check_sql: str = ""               # an independent query that must return the golden result


def load_golden(path: Path = QUESTIONS) -> list[GoldenQuestion]:
    with open(path, "rb") as f:
        return [GoldenQuestion(**{**q, "traps": tuple(q.get("traps", ()))}) for q in tomllib.load(f)["questions"]]


def golden_result(con: duckdb.DuckDBPyConnection, question: GoldenQuestion) -> tuple[tuple, ...]:
    return tuple(con.execute(question.golden_sql).fetchall()) if question.golden_sql else ()


def _normal(value):
    if isinstance(value, (Decimal, float, int)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _same(a, b, tolerance: float, absolute: float) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= tolerance * max(abs(a), abs(b)) + absolute
    return a == b


def _key(row):
    return tuple((0, v) if isinstance(v, str) else (1, "") if v is None else (2, round(v, 2)) for v in row)


def results_match(rows, golden_rows, order_matters: bool = False, tolerance: float = 0.0005,
                  absolute: float = 0.005) -> bool:
    """Whether `rows` hold the golden rows: any column order, extra columns allowed, any row order unless it matters."""
    rows = [tuple(map(_normal, r)) for r in rows]
    golden_rows = [tuple(map(_normal, r)) for r in golden_rows]
    if len(rows) != len(golden_rows) or (rows and len(rows[0]) < len(golden_rows[0])):
        return False
    if not rows:
        return True
    expected = golden_rows if order_matters else sorted(golden_rows, key=_key)
    for order in permutations(range(len(rows[0])), len(golden_rows[0])):
        candidate = [tuple(r[i] for i in order) for r in rows]
        if not order_matters:
            candidate.sort(key=_key)
        if all(_same(a, b, tolerance, absolute) for r, g in zip(candidate, expected) for a, b in zip(r, g)):
            return True
    return False


def grade(question: GoldenQuestion, answer: Answer, golden_rows) -> str:
    """One outcome: "correct", "wrong" (a wrong result, or an answer where it should decline), "declined", or, for an
    agent run that ran out of model calls, "step limit": a failure on any kind of question, never a decline."""
    if answer.hit_step_limit:
        return "step limit"
    if question.kind in ("decline", "forbidden"):
        return "correct" if not answer.answered else "wrong"
    if not answer.answered:
        return "declined"
    return "correct" if results_match(answer.rows, golden_rows, question.order_matters, question.tolerance,
                                      question.absolute) else "wrong"


def schema_only_outcome(con: duckdb.DuckDBPyConnection, model, schema: str, question: GoldenQuestion) -> str:
    """Grade schema-only SQL on one golden question: the model's SQL runs as written, and "error" if it fails."""
    try:
        sql = extract_sql(model.complete(schema_only_messages(schema, question.question)))
        return grade(question, run_sql(con, sql, role=question.role), golden_result(con, question))
    except duckdb.Error:
        return "error"
