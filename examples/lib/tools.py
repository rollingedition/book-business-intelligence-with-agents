"""The agent's tools. A model asks for a tool by name with JSON arguments; `Toolbox.call()` runs it.

Chapter 1 gives the agent two: `query_metric`, which computes a defined metric (`lib/metrics.py`), and
`cannot_answer`, which declines with a reason. Both end the run with an `Answer`. A call that fails, such as one that
names an unknown dimension, returns an error the model can read and doesn't end the run. Later chapters add tools here.

`extract_sql()` and `run_sql()` serve the schema-only path, where the model writes SQL and it runs as written.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import duckdb

from .answers import Answer, Provenance
from .metrics import MetricError, MetricRequest, query_metric


SQL_BLOCK = re.compile(r"```(?:sql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_sql(reply: str) -> str:
    """The SQL in a model's reply: the first fenced block, or the whole reply if it has none."""
    match = SQL_BLOCK.search(reply)
    return (match.group(1) if match else reply).strip().rstrip(";").strip()


def run_sql(con: duckdb.DuckDBPyConnection, sql: str, role: str = "analyst") -> Answer:
    """Run SQL as it is, with no checks, and return its result as an answer. Chapter 7 puts guards in front of this."""
    result = con.execute(sql)
    columns = tuple(c[0] for c in result.description)
    return Answer(columns=columns, rows=tuple(result.fetchall()),
                  provenance=Provenance(source="sql", sql=sql, role=role))


@dataclass(frozen=True)
class ToolResult:
    content: str                      # what the model is shown
    answer: Answer | None = None      # set when the tool's result ends the run


class Toolbox:
    def __init__(self, con: duckdb.DuckDBPyConnection, role: str = "analyst"):
        self.con, self.role = con, role
        self.tools = {"query_metric": self.query_metric, "cannot_answer": self.cannot_answer}

    def call(self, name: str, arguments: dict) -> ToolResult:
        if name not in self.tools:
            return ToolResult(f"error: unknown tool {name!r}; tools: {', '.join(self.tools)}")
        if not isinstance(arguments, dict):
            return ToolResult("error: arguments must be a JSON object")
        return self.tools[name](arguments)

    def query_metric(self, arguments: dict) -> ToolResult:
        try:
            answer = query_metric(self.con, MetricRequest.from_arguments(arguments), role=self.role)
        except (MetricError, duckdb.Error, TypeError) as e:
            return ToolResult(f"error: {e}")
        return ToolResult(answer.show(), answer)

    def cannot_answer(self, arguments: dict) -> ToolResult:
        reason = str(arguments.get("reason") or "no reason given")
        return ToolResult(f"declined: {reason}", Answer.decline(reason, role=self.role))
