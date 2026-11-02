"""Chapter 1's one defined metric, net revenue, and the code that turns a metric request into SQL.

A metric here is a name, a description a person can check, one aggregate over one mart, the rows it counts and the
dimensions it may be grouped and filtered by. A `MetricRequest` names a metric, the dimensions to group by and one
value per filtered dimension; `compile_request()` turns it into SQL. Dimension names come only from `DIMENSIONS`, and
filter values travel as query parameters, never pasted into the SQL text.

This is the rough version. Chapter 5 replaces it with a semantic layer (`lib/semantic.py`): many metrics, defined in
YAML, joined through entities. Net revenue's definition now comes from that YAML, so it exists once; the names here
and `compile_request()` stay as chapter 1 shows them, and later chapters compile requests with `lib/semantic.py`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import duckdb

from . import semantic
from .answers import Answer, Provenance
from .warehouse import data_as_of


@dataclass(frozen=True)
class Metric:
    name: str
    description: str
    table: str
    expression: str
    counts: str                       # the condition a row must meet to count


def _from_semantic_layer(name: str) -> Metric:
    """A metric as chapter 1 writes it, read from the semantic layer's YAML, so it is defined in one place."""
    layer = semantic.load()
    table, expression, counts = layer.simple_parts(name, alias="o")
    return Metric(name=name, description=layer.metrics[name].description, table=table, expression=expression,
                  counts=counts)


# Since chapter 5 this reads examples/data/semantic/metrics.yml: the table "analytics.fct_orders", the aggregate
# "sum(o.net_revenue_eur)" and the condition "o.status <> 'cancelled'", as chapter 1 shows them.
NET_REVENUE = _from_semantic_layer("net_revenue")
METRICS = {NET_REVENUE.name: NET_REVENUE}

# Each dimension's SQL, over the metric's mart (o) and the date dimension (d) joined on the local business day.
DIMENSIONS = {
    "region": "o.region",
    "channel": "o.channel",
    "fiscal_year": "d.fiscal_year",
    "fiscal_quarter": "d.fiscal_quarter",
    "calendar_year": "d.calendar_year",
    "calendar_month": "d.calendar_month",
}


class MetricError(ValueError):
    """A request names a metric or dimension that isn't defined."""


@dataclass(frozen=True)
class MetricRequest:
    metric: str
    group_by: tuple[str, ...] = ()
    filters: dict = field(default_factory=dict)

    @classmethod
    def from_arguments(cls, arguments: dict) -> "MetricRequest":
        return cls(metric=arguments.get("metric", ""), group_by=tuple(arguments.get("group_by") or ()),
                   filters=dict(arguments.get("filters") or {}))


def compile_request(request: MetricRequest) -> tuple[str, list]:
    """The SQL for a request, and its parameters. Raises MetricError for anything not defined."""
    if request.metric not in METRICS:
        raise MetricError(f"unknown metric {request.metric!r}; defined: {', '.join(METRICS)}")
    unknown = [d for d in (*request.group_by, *request.filters) if d not in DIMENSIONS]
    if unknown:
        raise MetricError(f"unknown dimension {unknown[0]!r}; defined: {', '.join(DIMENSIONS)}")
    metric = METRICS[request.metric]
    selected = [f"{DIMENSIONS[d]} AS {d}" for d in request.group_by]
    where = [metric.counts] + [f"{DIMENSIONS[d]} = ${i + 1}" for i, d in enumerate(request.filters)]
    sql = (f"SELECT {', '.join(selected + [f'round({metric.expression}, 2) AS {metric.name}'])}\n"
           f"FROM {metric.table} AS o\nJOIN analytics.dim_date AS d ON d.date_day = o.order_date_local\n"
           f"WHERE {' AND '.join(where)}")
    if request.group_by:
        columns = ", ".join(DIMENSIONS[d] for d in request.group_by)
        sql += f"\nGROUP BY {columns}\nORDER BY {columns}"
    return sql, list(request.filters.values())


def query_metric(con: duckdb.DuckDBPyConnection, request: MetricRequest, role: str = "analyst") -> Answer:
    """Run a metric request and return its answer with provenance."""
    sql, parameters = compile_request(request)
    result = con.execute(sql, parameters)
    columns = tuple(c[0] for c in result.description)
    rows = tuple(result.fetchall())
    provenance = Provenance(source="metric", sql=sql, metric=request.metric, filters=dict(request.filters), role=role,
                            data_as_of=data_as_of(con, METRICS[request.metric].table))
    return Answer(columns=columns, rows=rows, provenance=provenance)
