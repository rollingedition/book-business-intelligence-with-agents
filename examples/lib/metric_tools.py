"""Chapter 6's metrics-first tools: the agent sees the semantic layer's metrics and dimensions, never its tables.

`MetricToolbox` gives the agent five tools, each a method the loop in `lib/agent.py` calls by name:

- `list_metrics`: every metric with its description and the dimensions it can use, but not its type. The prompt
  carries this list, so the model doesn't spend a call on it; a host that serves the tools (chapter 11) can call it.
- `describe_metric`: one metric's type and definition, its dimensions, and the values of each categorical dimension.
- `query_metric`: a metric request, as JSON. `validate_request()` checks it against the layer and the warehouse
  before it compiles, and a request with problems comes back to the model as a list of them, with suggestions.
- `ask_back`: ends the run with a question to the person, when the question could mean several metrics or periods.
- `cannot_answer`: ends the run with a reason.

`validate_request()` catches what would otherwise fail late or, worse, run: a metric or dimension the layer doesn't
define for it (with the names that come close, or the metrics that can use it), a filter value no row has (with the
values that exist), a date that isn't the first day of its grain, which a truncated date never equals, and a period
written against a date dimension, such as "2026-03", which the compiler reads as March 1 alone. The last three
would run and return an empty or wrong result with no error.

`unbounded_ranking()` is a further check that `query_metric` doesn't run, because the recordings were made without it:
a request that orders its result but names no period, which ranks all-time totals.
"""
from __future__ import annotations

import re
from dataclasses import replace
from datetime import date
from difflib import get_close_matches

import duckdb

from .answers import Answer, Provenance
from .semantic import MetricRequest, SemanticLayer, load
from .tools import ToolResult

MAX_VALUES = 12                       # a categorical dimension with more values than this lists none of them


def _owner(layer: SemanticLayer, entity: str):
    """The semantic model where `entity` is primary or unique, which is where its dimensions live."""
    return next((m for m in layer.semantic_models.values() if m.primary_entity == entity), None)


def dimension_values(layer: SemanticLayer, con: duckdb.DuckDBPyConnection, name: str) -> list | None:
    """The values a dimension takes in the warehouse, or None for a time dimension at a standard grain."""
    parts = name.split("__")
    if parts[0] == "metric_time":
        column = layer.time_spine["custom"].get(parts[-1])
        if column is None:
            return None
        sql = f"SELECT DISTINCT {column} FROM {layer.time_spine['table']} ORDER BY 1"
    else:
        model = _owner(layer, parts[-2])
        dimension = model.dimensions[parts[-1]]
        if dimension.type == "time":
            return None
        sql = f"SELECT DISTINCT {dimension.expr} FROM {model.table} WHERE {dimension.expr} IS NOT NULL ORDER BY 1"
    return [row[0] for row in con.execute(sql).fetchall()]


def _first_day(value) -> date | None:
    """A time filter's value as a date: 2025 is 2025-01-01, "2026-03" is 2026-03-01. None if it isn't a date."""
    if isinstance(value, int) and not isinstance(value, bool):
        value = f"{value}-01-01"
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}", value):
        value = f"{value}-01"
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _starts_its_grain(day: date, grain: str) -> bool:
    return {"day": True, "week": day.weekday() == 0, "month": day.day == 1,
            "quarter": day.day == 1 and day.month in (1, 4, 7, 10),
            "year": (day.month, day.day) == (1, 1)}[grain]


def _is_day(value) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)) and _first_day(value) is not None


def _filter_problems(layer: SemanticLayer, con: duckdb.DuckDBPyConnection, name: str, value) -> list[str]:
    """What's wrong with one filter: a value no row has, or a date that would match a single day, or none."""
    parts, values = name.split("__"), value if isinstance(value, list) else [value]
    if parts[0] != "metric_time":
        if _owner(layer, parts[-2]).dimensions[parts[-1]].type == "time":
            if isinstance(value, list) or not _is_day(value):
                return [f"{name} = {value!r}: a date dimension matches single days only; for a period, filter "
                        f"metric_time at its grain, as metric_time__month = \"2026-03\" or metric_time__year = 2025"]
            return []
    known, grain, problems = dimension_values(layer, con, name), parts[-1], []
    for v in values:
        if known is not None:
            if str(v) not in {str(k) for k in known}:
                listed = ", ".join(map(str, known)) if len(known) <= MAX_VALUES else f"{len(known)} values"
                problems.append(f"no row has {name} = {v!r}; its values: {listed}")
            continue
        day = _first_day(v)
        if day is None:
            problems.append(f"{name} = {v!r} isn't a date; write a year as 2025, a month as \"2026-03\"")
        elif grain == "day" and not _is_day(v):
            problems.append(f"{name} = {v!r} isn't one day; write a day as \"2026-01-01\"")
        elif not _starts_its_grain(day, grain):
            problems.append(f"{name} = {v!r} isn't the first day of a {grain}, so no {grain} equals it")
    return problems


def normalize_request(request: MetricRequest) -> MetricRequest:
    """The request with a year written as text, such as "2025", turned into the number 2025, which it can only mean."""
    def year(name, value):
        if name.startswith("metric_time__") and isinstance(value, str) and re.fullmatch(r"\d{4}", value):
            return int(value)
        return [year(name, v) for v in value] if isinstance(value, list) else value
    return replace(request, filters={name: year(name, value) for name, value in request.filters.items()})


def validate_request(layer: SemanticLayer, con: duckdb.DuckDBPyConnection, request: MetricRequest) -> list[str]:
    """Every problem in a request, checked against the layer's definitions and the warehouse's values."""
    unknown = [m for m in request.metrics if m not in layer.metrics]
    if not request.metrics:
        return ["a request needs at least one metric"]
    if unknown:
        return [f"unknown metric {m!r}" + _suggest(m, list(layer.metrics)) for m in unknown]
    allowed = set.intersection(*(set(layer.dimensions_for(m)) for m in request.metrics))
    problems = []
    for name in dict.fromkeys([*request.group_by, *request.filters]):
        if name in allowed:
            continue
        others = [m for m in layer.metrics if name in layer.dimensions_for(m)]
        close = get_close_matches(name, sorted(allowed), n=2, cutoff=0.85)
        hint = (f"; did you mean {' or '.join(close)}?" if close else
                f"; metrics that can use it: {', '.join(others)}" if others else "; no metric defines it")
        problems.append(f"{', '.join(request.metrics)} can't use dimension {name!r}{hint}")
    for name, value in request.filters.items():
        if name in allowed:
            problems += _filter_problems(layer, con, name, value)
    for name in request.order_by:
        if name.lstrip("-") not in {*request.group_by, *request.metrics}:
            problems.append(f"can't order by {name.lstrip('-')!r}: it isn't a requested metric or group-by")
    if request.limit is not None and (not isinstance(request.limit, int) or isinstance(request.limit, bool)
                                      or request.limit < 1):
        problems.append("limit must be a positive whole number")
    return problems


def unbounded_ranking(request: MetricRequest) -> str | None:
    """The problem with a request that orders its result but filters or groups by no metric_time grain, or None."""
    timed = any(name.startswith("metric_time__") for name in [*request.filters, *request.group_by])
    if request.order_by and not timed:
        return "the request ranks its result but names no period; filter or group by a metric_time grain"
    return None


def _suggest(name: str, names: list[str]) -> str:
    close = get_close_matches(name, names, n=2, cutoff=0.6)
    return f"; did you mean {' or '.join(close)}?" if close else f"; defined: {', '.join(names)}"


def catalog(layer: SemanticLayer) -> str:
    """`list_metrics` as text: one line per metric, with its description and the dimensions other than time."""
    lines = []
    for metric in layer.metrics.values():
        dimensions = [d for d in layer.dimensions_for(metric.name) if not d.startswith("metric_time__")]
        lines.append(f"- {metric.name}: {metric.description} Dimensions: {', '.join(dimensions)}")
    return "\n".join(lines)


class MetricToolbox:
    """The metrics-first tools over one warehouse connection and one semantic layer, for one role."""

    def __init__(self, con: duckdb.DuckDBPyConnection, layer: SemanticLayer | None = None, role: str = "analyst"):
        self.con, self.layer, self.role = con, layer or load(), role
        self.rejected: list[list[str]] = []          # the problems of every request validation sent back
        self.tools = {"list_metrics": self.list_metrics, "describe_metric": self.describe_metric,
                      "query_metric": self.query_metric, "ask_back": self.ask_back,
                      "cannot_answer": self.cannot_answer}

    def call(self, name: str, arguments: dict) -> ToolResult:
        if name not in self.tools:
            return ToolResult(f"error: unknown tool {name!r}; tools: {', '.join(self.tools)}")
        if not isinstance(arguments, dict):
            return ToolResult("error: arguments must be a JSON object")
        return self.tools[name](arguments)

    def list_metrics(self, arguments: dict) -> ToolResult:
        return ToolResult(catalog(self.layer))

    def describe_metric(self, arguments: dict) -> ToolResult:
        name = str(arguments.get("metric") or "")
        if name not in self.layer.metrics:
            return ToolResult(f"error: unknown metric {name!r}" + _suggest(name, list(self.layer.metrics)))
        metric, lines = self.layer.metrics[name], []
        for dimension in self.layer.dimensions_for(name):
            values = dimension_values(self.layer, self.con, dimension)
            shown = f": {', '.join(map(str, values))}" if values and len(values) <= MAX_VALUES else ""
            lines.append(f"- {dimension}{shown}")
        return ToolResult(f"{name}, a {metric.type} metric: {metric.description}\nDimensions:\n" + "\n".join(lines))

    def query_metric(self, arguments: dict) -> ToolResult:
        arguments = {k: [v] if k in ("metrics", "group_by", "order_by") and isinstance(v, str) else v
                     for k, v in arguments.items()}
        try:
            request = MetricRequest.from_arguments(arguments)
        except (TypeError, ValueError) as e:
            return ToolResult(f"error: the request isn't valid: {e}")
        request = normalize_request(request)
        problems = validate_request(self.layer, self.con, request)
        if problems:
            self.rejected.append(problems)
            return ToolResult("error: request rejected: " + "; ".join(problems))
        try:
            answer = self.layer.query(self.con, request, role=self.role)
        except (ValueError, duckdb.Error) as e:      # SemanticError is a ValueError
            return ToolResult(f"error: {e}")
        return ToolResult(answer.show(), answer)

    def ask_back(self, arguments: dict) -> ToolResult:
        question = str(arguments.get("question") or "").strip()
        if not question:
            return ToolResult('error: ask_back needs a "question" for the person')
        options = arguments.get("options") or []
        options = [options] if isinstance(options, str) else [str(o) for o in options]
        described = [f"{o}: {self.layer.metrics[o].description}" if o in self.layer.metrics else o for o in options]
        text = "\n".join([question, *(f"- {d}" for d in described)])
        answer = Answer(reason=text, provenance=Provenance(source="ask_back", sql="", role=self.role))
        return ToolResult(f"asked: {text}", answer)

    def cannot_answer(self, arguments: dict) -> ToolResult:
        reason = str(arguments.get("reason") or "no reason given")
        return ToolResult(f"declined: {reason}", Answer.decline(reason, role=self.role))
