"""MetricFlow, run over the same YAML as `lib/semantic.py`, so chapter 5 can check the book's compiler against it.

`load_manifest()` parses `examples/data/semantic/*.yml` with MetricFlow's own parser and validator. `engine()` builds a
`MetricFlowEngine` with `DuckDbClient`, a small adapter that lets MetricFlow run SQL on the shop's warehouse.
`to_metricflow()` turns the book's `MetricRequest` into MetricFlow's request, and `explain_sql()` returns the SQL
MetricFlow writes for it. `as_dates()` turns the timestamps MetricFlow returns for a grain into dates.

`MetricFlowEngine` is MetricFlow's internal Python API: its own docstring says not to assume it is stable. Everything
that touches it is in this one module, so a MetricFlow release that changes it changes only this file and the one
example that uses it.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import duckdb
from metricflow.data_table.mf_table import MetricFlowDataTable
from metricflow.engine.metricflow_engine import MetricFlowEngine, MetricFlowQueryRequest
from metricflow.protocols.sql_client import SqlEngine
from metricflow.sql.render.duckdb_renderer import DuckDbSqlPlanRenderer
from metricflow_semantic_interfaces.parsing.dir_to_model import parse_directory_of_yaml_files_to_semantic_manifest
from metricflow_semantic_interfaces.validations.semantic_manifest_validator import SemanticManifestValidator
from metricflow_semantics.model.semantic_manifest_lookup import SemanticManifestLookup

from .semantic import SEMANTIC_DIR, STANDARD_GRAINS, MetricRequest


class DuckDbClient:
    """MetricFlow's `SqlClient` protocol over a DuckDB connection: which engine it is, its renderer, and running SQL."""

    sql_engine_type = SqlEngine.DUCKDB
    sql_plan_renderer = DuckDbSqlPlanRenderer()

    def __init__(self, con: duckdb.DuckDBPyConnection):
        self.con = con

    def query(self, stmt: str, sql_bind_parameter_set=None) -> MetricFlowDataTable:
        result = self.con.execute(stmt, self._parameters(sql_bind_parameter_set))
        return MetricFlowDataTable.create_from_rows([c[0] for c in result.description], result.fetchall())

    def execute(self, stmt: str, sql_bind_parameter_set=None) -> None:
        self.con.execute(stmt, self._parameters(sql_bind_parameter_set)).fetchall()

    def dry_run(self, stmt: str, sql_bind_parameter_set=None) -> None:
        self.con.execute(f"EXPLAIN {stmt}", self._parameters(sql_bind_parameter_set)).fetchall()

    def close(self) -> None:
        pass

    def render_bind_parameter_key(self, bind_parameter_key: str) -> str:
        return f"${bind_parameter_key}"

    @staticmethod
    def _parameters(parameter_set) -> dict:
        if parameter_set is None:
            return {}
        return {item.key: item.value.value for item in parameter_set.param_items}


def load_manifest(folder: Path = SEMANTIC_DIR):
    """Parse and validate the YAML with MetricFlow. Raises if MetricFlow finds an error."""
    manifest = parse_directory_of_yaml_files_to_semantic_manifest(str(folder)).semantic_manifest
    results = SemanticManifestValidator().validate_semantic_manifest(manifest)
    if results.has_blocking_issues:
        raise ValueError("; ".join(issue.message for issue in results.errors))
    return manifest


def engine(con: duckdb.DuckDBPyConnection, folder: Path = SEMANTIC_DIR) -> MetricFlowEngine:
    return MetricFlowEngine(SemanticManifestLookup(load_manifest(folder)), DuckDbClient(con))


def _condition(name: str, value) -> str:
    """One filter in MetricFlow's where-filter syntax. Values come from the book's own examples, not from a model."""
    parts = name.split("__")
    if parts[0] == "metric_time":
        grain = parts[1]
        if grain in STANDARD_GRAINS and isinstance(value, int):
            value = f"{value}-01-01"
        if grain in STANDARD_GRAINS and isinstance(value, str) and len(value) == 7:
            value = f"{value}-01"
        reference = f"{{{{ TimeDimension('metric_time', '{grain}') }}}}"
    else:
        reference = f"{{{{ Dimension('{name}') }}}}"
    values = value if isinstance(value, (list, tuple)) else [value]
    literals = ", ".join(repr(v) if isinstance(v, str) else str(v) for v in values)
    return f"{reference} = {literals}" if len(values) == 1 else f"{reference} IN ({literals})"


def to_metricflow(request: MetricRequest) -> MetricFlowQueryRequest:
    """The book's metric request as MetricFlow's: the same metric and dimension names, filters as where-filters."""
    return MetricFlowQueryRequest.create(
        metric_names=list(request.metrics), group_by_names=list(request.group_by),
        where_constraints=[_condition(n, v) for n, v in request.filters.items()] or None,
        order_by_names=list(request.order_by or request.group_by) or None, limit=request.limit)


def explain_sql(mf: MetricFlowEngine, request: MetricRequest) -> str:
    """The SQL MetricFlow writes for a request, without running it."""
    return mf.explain(to_metricflow(request)).sql_statement.sql


def as_dates(rows):
    """MetricFlow returns a month or year as a timestamp at midnight; the book's compiler returns a date."""
    return [tuple(v.date() if isinstance(v, datetime) else v for v in row) for row in rows]
