"""A small subset of DABstep, a public benchmark for data agents, loaded into DuckDB for chapter 3.

DABstep (Data Agent Benchmark for Multi-step Reasoning) asks questions about a payments processor's transactions and
scores the final answer, a short string or number, not the SQL. The subset in `examples/data/dabstep/` holds three of
its public dev tasks (`tasks.jsonl`) and its payments table without four identifier columns (`payments.csv.gz`);
`SOURCE.md` there names the source, the pinned revision, the licence (CC BY 4.0) and every change.

`connect()` loads the payments into a read-only DuckDB database, as `lib/warehouse.py` does for the shop.
`answer_task()` runs the schema-only approach on one task: the model writes SQL, the SQL runs, and the model turns
the result into a final answer in the format the task asks for. `answers_match()` compares a final answer with the
task's answer: case and surrounding spaces don't matter, and numbers must agree within a small tolerance. It is a
simplified form of DABstep's own scoring, which normalizes each answer by its type.
"""
from __future__ import annotations

import atexit
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import duckdb

from .model import Model
from .prompts import DABSTEP_FINAL, dabstep_sql_messages
from .tools import extract_sql, run_sql
from .warehouse import READ_ONLY_SETTINGS, describe_schema

FOLDER = Path(__file__).resolve().parent.parent / "data" / "dabstep"
REVISION = "1d740a52b8a41ba6fdd4d4435120a0429023dd24"


@dataclass(frozen=True)
class Task:
    task_id: str
    question: str
    guidelines: str
    level: str
    answer: str


@dataclass(frozen=True)
class TaskRun:
    task: Task
    sql: str
    result: str                       # the query's result as the model saw it, or the error
    answer: str                       # the model's final answer

    @property
    def correct(self) -> bool:
        return answers_match(self.answer, self.task.answer)


def load_tasks() -> list[Task]:
    lines = (FOLDER / "tasks.jsonl").read_text(encoding="utf-8").splitlines()
    return [Task(**{k: str(v) for k, v in json.loads(line).items() if k in Task.__dataclass_fields__})
            for line in lines if line.strip()]


def connect() -> duckdb.DuckDBPyConnection:
    """The payments table, `payments`, in a read-only DuckDB database."""
    folder = Path(tempfile.mkdtemp(prefix="dabstep-"))
    atexit.register(shutil.rmtree, folder, ignore_errors=True)
    path = folder / "dabstep.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE TABLE payments AS SELECT * FROM read_csv(?)", [str(FOLDER / "payments.csv.gz")])
    return duckdb.connect(str(path), read_only=True, config=READ_ONLY_SETTINGS)


def answer_task(con: duckdb.DuckDBPyConnection, model: Model, task: Task) -> TaskRun:
    """Two model calls: SQL for the task, then a final answer from the SQL's result, in the task's format."""
    messages = dabstep_sql_messages(describe_schema(con, ("main",)), task.question)
    reply = model.complete(messages)
    sql = extract_sql(reply)
    try:
        result = run_sql(con, sql).show()
    except duckdb.Error as e:
        result = f"error: {e}"
    follow_up = DABSTEP_FINAL.format(result=result, guidelines=task.guidelines)
    answer = model.complete(messages + [{"role": "assistant", "content": reply}, {"role": "user", "content": follow_up}])
    return TaskRun(task, sql, result, answer.strip())


def _normal(text: str) -> str:
    return " ".join(text.strip().strip("'\"`").rstrip(".").lower().split())


def answers_match(answer: str, expected: str) -> bool:
    """Whether a final answer equals the expected one, ignoring case and spaces; numbers within 1e-6, relative."""
    a, e = _normal(answer), _normal(expected)
    try:
        return abs(float(a) - float(e)) <= 1e-6 * max(1.0, abs(float(e)))
    except ValueError:
        return a == e
