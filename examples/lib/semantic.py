"""The book's semantic layer: the shop's metrics defined once, in YAML, and compiled to SQL through sqlglot.

`load()` reads `examples/data/semantic/*.yml`, the same files MetricFlow reads (`lib/metricflow_bridge.py`), and
validates them. The YAML is MetricFlow's standalone shape: one `semantic_model:`, `metric:` or `project_configuration:`
per document, tables named by `node_relation`, and simple metrics that name their semantic model and aggregation
directly, with no measures.

A `MetricRequest` names metrics, the dimensions to group by, one value or a list of values per filtered dimension, an
order and a limit. Dimension names are MetricFlow's: `order__region` is the `region` dimension of the semantic model
whose primary entity is `order`; `order__customer__region` reaches it through two entities; `metric_time__month` is
each metric's own time dimension at a grain, and `metric_time__fiscal_quarter` a custom grain from the time spine.

`SemanticLayer.compile()` builds a sqlglot expression, so the SQL can be written in any dialect sqlglot supports. It
joins a metric's semantic model to another only through an entity that is unique there (many rows to one), so a sum
can't fan out: a request that would need a join to many rows is refused with `FanOutError`. Each metric of a ratio or
derived metric, or of a request for several metrics, is aggregated on its own and the results are joined on the
group-by dimensions. Filter values become SQL literals in the expression tree, never text pasted into SQL.

This compiler handles the subset of the spec the shop uses: simple, ratio and derived metrics; sum, count,
count_distinct, average, min and max; categorical and time dimensions; joins up to two entities away; day, week, month,
quarter and year grains and the time spine's custom grains. Anything else is refused when the YAML is loaded.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import duckdb
import sqlglot
import yaml
from sqlglot import exp

from .answers import Answer, Provenance
from .warehouse import data_as_of

SEMANTIC_DIR = Path(__file__).resolve().parent.parent / "data" / "semantic"
STANDARD_GRAINS = ("day", "week", "month", "quarter", "year")
AGGREGATIONS = {"sum": "SUM", "count": "COUNT", "count_distinct": "COUNT", "average": "AVG", "min": "MIN",
                "max": "MAX"}
MAX_HOPS = 2
UNIQUE = ("primary", "unique")
TEMPLATE = re.compile(r"\{\{\s*(Dimension|TimeDimension|Entity)\(\s*'([^']+)'\s*(?:,\s*'([^']+)'\s*)?\)\s*\}\}")


class SemanticError(ValueError):
    """The YAML or a request names something the layer doesn't define, or asks for what it can't compile."""


class FanOutError(SemanticError):
    """A request would join a metric's rows to many rows of another model, and repeat them in the sum."""


@dataclass(frozen=True)
class Entity:
    name: str
    type: str                         # primary, unique, foreign or natural
    expr: str


@dataclass(frozen=True)
class Dimension:
    name: str
    type: str                         # categorical or time
    expr: str
    grain: str | None = None          # a time dimension's grain


@dataclass(frozen=True)
class SemanticModel:
    name: str
    table: str                        # schema.alias, from node_relation
    description: str = ""
    entities: dict[str, Entity] = field(default_factory=dict)
    dimensions: dict[str, Dimension] = field(default_factory=dict)
    agg_time_dimension: str | None = None

    @property
    def primary_entity(self) -> str | None:
        return next((e.name for e in self.entities.values() if e.type in UNIQUE), None)


@dataclass(frozen=True)
class MetricInput:
    name: str                         # the metric this input reads
    alias: str | None = None
    filter: str | None = None

    @property
    def column(self) -> str:
        return self.alias or self.name


@dataclass(frozen=True)
class Metric:
    name: str
    type: str                         # simple, ratio or derived
    description: str = ""
    filter: str | None = None
    semantic_model: str | None = None  # simple metrics: where the rows come from, how they're aggregated
    expr: str | None = None
    agg: str | None = None
    agg_time_dimension: str | None = None
    numerator: MetricInput | None = None    # ratio metrics
    denominator: MetricInput | None = None
    inputs: tuple[MetricInput, ...] = ()    # derived metrics, combined by `expr`


@dataclass(frozen=True)
class MetricRequest:
    metrics: tuple[str, ...]
    group_by: tuple[str, ...] = ()
    filters: dict = field(default_factory=dict)   # dimension name -> one value, or a list of values
    order_by: tuple[str, ...] = ()                # names, "-" first for descending; default: the group-by order
    limit: int | None = None

    @classmethod
    def from_arguments(cls, arguments: dict) -> "MetricRequest":
        metrics = arguments.get("metrics") or arguments.get("metric") or ()
        return cls(metrics=(metrics,) if isinstance(metrics, str) else tuple(metrics),
                   group_by=tuple(arguments.get("group_by") or ()), filters=dict(arguments.get("filters") or {}),
                   order_by=tuple(arguments.get("order_by") or ()), limit=arguments.get("limit"))


@dataclass
class _Scope:
    """One simple metric's FROM clause while it compiles: its model, and the joins its dimensions needed."""
    model: SemanticModel
    joins: dict = field(default_factory=dict)     # entity path -> (alias, model, join condition)
    calendar: bool = False

    @property
    def alias(self) -> str:
        return self.model.name


def _qualify(sql: str, alias: str) -> exp.Expression:
    """Parse a column expression from the YAML and qualify its bare columns with the model's alias."""
    tree = sqlglot.parse_one(sql, dialect="duckdb")
    for column in list(tree.find_all(exp.Column)):
        if not column.table:
            column.set("table", exp.to_identifier(alias))
    return tree


def _literal(value, grain: str | None) -> exp.Expression:
    """A filter value as a SQL literal. Standard grains compare dates: 2025 is 2025-01-01, '2026-03' is 2026-03-01."""
    if grain in STANDARD_GRAINS:
        if isinstance(value, int) and not isinstance(value, bool):
            value = f"{value}-01-01"
        if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}", value):
            value = f"{value}-01"
        return exp.cast(exp.Literal.string(date.fromisoformat(str(value)).isoformat()), "DATE")
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise SemanticError(f"filter value {value!r} must be text or a number")
    return exp.convert(value)


class SemanticLayer:
    def __init__(self, models: dict[str, SemanticModel], metrics: dict[str, Metric], time_spine: dict):
        self.semantic_models, self.metrics, self.time_spine = models, metrics, time_spine
        self._validate()

    # Loading and validating ---------------------------------------------------------------------------------

    def _validate(self) -> None:
        issues = []
        for model in self.semantic_models.values():
            if sum(e.type in UNIQUE for e in model.entities.values()) > 1:
                issues.append(f"semantic model {model.name!r} has more than one primary or unique entity")
        for metric in self.metrics.values():
            try:
                if metric.type == "simple":
                    model = self.semantic_models.get(metric.semantic_model)
                    if model is None:
                        raise SemanticError(f"unknown semantic model {metric.semantic_model!r}")
                    if metric.agg not in AGGREGATIONS:
                        raise SemanticError(f"aggregation {metric.agg!r} isn't supported")
                    self._time_dimension(metric)
                    for template in filter(None, [metric.filter]):
                        self._render_filter(template, _Scope(model), metric)
                elif metric.type in ("ratio", "derived"):
                    inputs = self._inputs(metric)
                    for i in inputs:
                        if self.metrics.get(i.name) is None or self.metrics[i.name].type != "simple":
                            raise SemanticError(f"input {i.name!r} must be a simple metric")
                    if metric.type == "derived":
                        used = {c.name for c in sqlglot.parse_one(metric.expr).find_all(exp.Column)}
                        if used != {i.column for i in inputs}:
                            raise SemanticError(f"expr {metric.expr!r} must use exactly its inputs")
                else:
                    raise SemanticError(f"metric type {metric.type!r} isn't supported")
            except SemanticError as e:
                issues.append(f"metric {metric.name!r}: {e}")
        if issues:
            raise SemanticError("; ".join(issues))

    def check(self, con: duckdb.DuckDBPyConnection) -> list[str]:
        """Check the definitions against the warehouse: every expression runs, and every primary entity is unique."""
        problems = []
        for model in self.semantic_models.values():
            columns = [e.expr for e in model.entities.values()] + [d.expr for d in model.dimensions.values()]
            try:
                con.execute(f"SELECT {', '.join(columns)} FROM {model.table} LIMIT 0").fetchall()
            except duckdb.Error as e:
                problems.append(f"{model.name}: {str(e).splitlines()[0]}")
                continue
            key = model.entities.get(model.primary_entity)
            if key:
                (repeats,), = con.execute(f"SELECT count(*) - count(DISTINCT {key.expr}) FROM {model.table}").fetchall()
                if repeats:
                    problems.append(f"{model.name}: primary entity {key.name!r} repeats in {repeats:,} rows")
        for metric in self.metrics.values():
            if metric.type == "simple":
                try:
                    con.execute(self.sql(MetricRequest((metric.name,))) + " LIMIT 0").fetchall()
                except duckdb.Error as e:
                    problems.append(f"{metric.name}: {str(e).splitlines()[0]}")
        return problems

    # Describing ---------------------------------------------------------------------------------------------

    def simple_metrics_for(self, name: str) -> tuple[MetricInput, ...]:
        metric = self._metric(name)
        return (MetricInput(name),) if metric.type == "simple" else self._inputs(metric)

    def dimensions_for(self, name: str) -> list[str]:
        """Every group-by name the metric can use: those every simple metric it reads can reach without fan-out."""
        names = None
        for i in self.simple_metrics_for(name):
            reachable = set(self._reachable(self.semantic_models[self.metrics[i.name].semantic_model]))
            names = reachable if names is None else names & reachable
        grains = [f"metric_time__{g}" for g in (*STANDARD_GRAINS, *self.time_spine["custom"])]
        return grains + sorted(names or ())

    def _reachable(self, model: SemanticModel, path: tuple = (), seen: tuple = ()):
        if not path and model.primary_entity:
            yield from (f"{model.primary_entity}__{d}" for d in model.dimensions)
        if len(path) == MAX_HOPS:
            return
        for entity in model.entities.values():
            target = self._owner(entity.name)
            if target and target.name != model.name and target.name not in seen:
                yield from (f"{'__'.join((*path, entity.name))}__{d}" for d in target.dimensions)
                yield from self._reachable(target, (*path, entity.name), (*seen, model.name))

    # Compiling ----------------------------------------------------------------------------------------------

    def compile(self, request: MetricRequest) -> exp.Select:
        """The SQL for a request, as a sqlglot expression. Raises SemanticError for anything it can't compile."""
        if not request.metrics:
            raise SemanticError("a request needs at least one metric")
        metrics = [self._metric(m) for m in request.metrics]
        inputs = list(dict.fromkeys(i for m in metrics for i in self.simple_metrics_for(m.name)))
        if len({i.column for i in inputs}) != len(inputs):
            raise SemanticError("two inputs of this request share a name; ask for the metrics separately")
        keys = list(request.group_by)
        if len(metrics) == 1 and metrics[0].type == "simple":
            query = self._aggregate(inputs[0], keys, request.filters)
        else:
            query = self._combine(metrics, inputs, keys, request.filters)
        return self._order(query, request, keys)

    def sql(self, request: MetricRequest, dialect: str = "duckdb", pretty: bool = True, **options) -> str:
        """The SQL for a request in a sqlglot dialect, such as duckdb, snowflake, bigquery, databricks or tsql."""
        return self.compile(request).sql(dialect=dialect, pretty=pretty, **options)

    def query(self, con: duckdb.DuckDBPyConnection, request: MetricRequest, role: str = "analyst") -> Answer:
        """Run a request on the warehouse and return its answer with provenance."""
        sql = self.sql(request)
        result = con.execute(sql)
        columns = tuple(c[0] for c in result.description)
        rows = tuple(result.fetchall())
        tables = {self.semantic_models[self.metrics[i.name].semantic_model].table
                  for m in request.metrics for i in self.simple_metrics_for(m)}
        provenance = Provenance(source="metric", sql=sql, metric=", ".join(request.metrics),
                                filters=dict(request.filters), role=role,
                                data_as_of=min(data_as_of(con, t) for t in sorted(tables)))
        return Answer(columns=columns, rows=rows, provenance=provenance)

    def simple_parts(self, name: str, alias: str) -> tuple[str, str, str | None]:
        """A simple metric over its own model as (table, aggregate, condition) SQL text, its columns under `alias`."""
        metric = self._metric(name)
        if metric.type != "simple":
            raise SemanticError(f"{name!r} isn't a simple metric")
        model = self.semantic_models[metric.semantic_model]
        scope = _Scope(model)
        aggregate = self._aggregate_expression(metric, scope)
        condition = self._render_filter(metric.filter, scope, metric) if metric.filter else None
        if scope.joins:
            raise SemanticError(f"{name!r} filters on another model, so it has no single-table form")
        rename = lambda e: e.transform(lambda n: exp.column(n.name, alias) if isinstance(n, exp.Column) else n)
        render = lambda e: rename(e).sql(dialect="duckdb", normalize_functions="lower")
        return model.table, render(aggregate), render(condition) if condition is not None else None

    def _metric(self, name: str) -> Metric:
        if name not in self.metrics:
            raise SemanticError(f"unknown metric {name!r}; defined: {', '.join(self.metrics)}")
        return self.metrics[name]

    def _inputs(self, metric: Metric) -> tuple[MetricInput, ...]:
        return (metric.numerator, metric.denominator) if metric.type == "ratio" else metric.inputs

    def _owner(self, entity: str) -> SemanticModel | None:
        """The semantic model where `entity` is unique: the one side of a many-to-one join."""
        return next((m for m in self.semantic_models.values()
                     if entity in m.entities and m.entities[entity].type in UNIQUE), None)

    def _time_dimension(self, metric: Metric) -> Dimension:
        model = self.semantic_models[metric.semantic_model]
        name = metric.agg_time_dimension or model.agg_time_dimension
        dimension = model.dimensions.get(name)
        if dimension is None or dimension.type != "time":
            raise SemanticError(f"{model.name!r} has no time dimension {name!r} for {metric.name!r}")
        return dimension

    def _join(self, scope: _Scope, path: tuple[str, ...], metric: Metric) -> tuple[str, SemanticModel]:
        """Walk entity links from the metric's model, adding a many-to-one join for each; refuse a fan-out."""
        alias, model = scope.alias, scope.model
        for depth in range(len(path)):
            entity = path[depth]
            if depth == len(path) - 1 and entity == model.primary_entity:
                break                                   # the dimension is on this model: no join
            target = self._owner(entity)
            if entity not in model.entities or target is None or target.name == model.name:
                self._refuse(model, entity, metric)
            if depth + 1 > MAX_HOPS:
                raise SemanticError(f"{'__'.join(path)} is more than {MAX_HOPS} joins away from {metric.name!r}")
            key = path[:depth + 1]
            if key not in scope.joins:
                join_alias = target.name if all(a != target.name for a, _, _ in scope.joins.values()) \
                    else f"{target.name}_{len(scope.joins)}"
                on = exp.EQ(this=_qualify(model.entities[entity].expr, alias),
                            expression=_qualify(target.entities[entity].expr, join_alias))
                scope.joins[key] = (join_alias, target, on)
            alias, model = scope.joins[key][0], target
        return alias, model

    def _refuse(self, model: SemanticModel, entity: str, metric: Metric):
        key = model.primary_entity
        many = [m.name for m in self.semantic_models.values() if entity in m.entities and key in m.entities
                and m.name != model.name and m.entities[key].type not in UNIQUE]
        if many:
            others = [n for n, m in self.metrics.items() if m.type == "simple" and m.semantic_model == many[0]]
            raise FanOutError(f"{metric.name!r} is summed per {key}, but {entity!r} is reached through "
                              f"{many[0]!r}, which has many rows per {key}; each {key} would count once per row. "
                              f"Use a metric defined on {many[0]!r}: {', '.join(others) or 'none is defined'}")
        raise SemanticError(f"{model.name!r} has no join to an entity {entity!r} for {metric.name!r}")

    def _resolve(self, name: str, scope: _Scope, metric: Metric) -> tuple[exp.Expression, str | None]:
        """A group-by or filter name as a SQL expression in `scope`, with its time grain if it has one."""
        parts = name.split("__")
        if parts[0] == "metric_time":
            grain = parts[1] if len(parts) > 1 else "day"
            column = _qualify(self._time_dimension(metric).expr, scope.alias)
            if grain == "day":
                return column, grain
            if grain in STANDARD_GRAINS:
                # The column is cast to DATE first, so sqlglot builds a date truncation: BigQuery then gets
                # DATE_TRUNC, which takes a DATE, rather than TIMESTAMP_TRUNC, which doesn't.
                truncated = sqlglot.parse_one(f"DATE_TRUNC('{grain}', CAST(_time AS DATE))", dialect="duckdb")
                truncated = truncated.transform(lambda n: column if isinstance(n, exp.Column) else n)
                return exp.cast(truncated, "DATE"), grain
            if grain in self.time_spine["custom"]:
                scope.calendar = True
                return exp.column(self.time_spine["custom"][grain], "calendar"), grain
            raise SemanticError(f"unknown time grain {grain!r}; grains: "
                                f"{', '.join((*STANDARD_GRAINS, *self.time_spine['custom']))}")
        if len(parts) < 2:
            raise SemanticError(f"dimension {name!r} needs an entity, as in order__region")
        alias, model = self._join(scope, tuple(parts[:-1]), metric)
        dimension = model.dimensions.get(parts[-1])
        if dimension is None:
            raise SemanticError(f"unknown dimension {name!r}; {metric.name!r} can use: "
                                f"{', '.join(self.dimensions_for(metric.name))}")
        return _qualify(dimension.expr, alias), dimension.grain if dimension.type == "time" else None

    def _render_filter(self, template: str, scope: _Scope, metric: Metric) -> exp.Expression:
        """A MetricFlow filter, such as {{ Dimension('order__status') }} != 'cancelled', as a SQL condition."""
        refs = {}

        def placeholder(match):
            kind, name, grain = match.groups()
            refs[f"_ref{len(refs)}"] = f"{name}__{grain}" if kind == "TimeDimension" and grain else name
            return f"_ref{len(refs) - 1}"

        tree = sqlglot.parse_one(TEMPLATE.sub(placeholder, template), dialect="duckdb")
        return tree.transform(lambda n: self._resolve(refs[n.name], scope, metric)[0]
                              if isinstance(n, exp.Column) and n.name in refs else n)

    def _aggregate_expression(self, metric: Metric, scope: _Scope) -> exp.Expression:
        value = _qualify(metric.expr, scope.alias)
        if metric.agg == "count_distinct":
            value = exp.Distinct(expressions=[value])
        return exp.func(AGGREGATIONS[metric.agg], value)

    def _aggregate(self, i: MetricInput, keys: list[str], filters: dict) -> exp.Select:
        """One simple metric, aggregated by the group-by keys, from its model and the joins its dimensions need."""
        metric = self.metrics[i.name]
        scope = _Scope(self.semantic_models[metric.semantic_model])
        selected = [self._resolve(k, scope, metric)[0].as_(k) for k in keys]
        conditions = [self._render_filter(f, scope, metric) for f in (metric.filter, i.filter) if f]
        for name, value in filters.items():
            column, grain = self._resolve(name, scope, metric)
            values = value if isinstance(value, (list, tuple)) else [value]
            if not values:
                raise SemanticError(f"filter {name!r} has no values")
            literals = [_literal(v, grain) for v in values]
            conditions.append(exp.EQ(this=column, expression=literals[0]) if len(literals) == 1
                              else exp.In(this=column, expressions=literals))
        query = exp.select(*selected, self._aggregate_expression(metric, scope).as_(i.column)) \
            .from_(exp.to_table(scope.model.table).as_(scope.alias))
        for join_alias, target, on in scope.joins.values():
            query = query.join(exp.to_table(target.table).as_(join_alias), on=on, join_type="left")
        if scope.calendar:
            time = _qualify(self._time_dimension(metric).expr, scope.alias)
            query = query.join(exp.to_table(self.time_spine["table"]).as_("calendar"), join_type="left",
                               on=exp.EQ(this=exp.column(self.time_spine["column"], "calendar"), expression=time))
        if conditions:
            query = query.where(exp.and_(*conditions))
        if keys:
            query = query.group_by(*[e.this.copy() for e in selected])
        return query

    def _combine(self, metrics: list[Metric], inputs: list[MetricInput], keys: list[str], filters: dict):
        """Aggregate each simple metric on its own, join the results on the keys, then compute each metric."""
        query = exp.select()
        for n, i in enumerate(inputs):
            query = query.with_(i.column, as_=self._aggregate(i, keys, filters))
            if n == 0:
                query = query.from_(i.column)
            elif keys:
                on = exp.and_(*[exp.EQ(this=exp.column(k, i.column),
                                       expression=self._coalesce([x.column for x in inputs[:n]], k)) for k in keys])
                query = query.join(i.column, on=on, join_type="full outer")
            else:
                query = query.join(i.column, join_type="cross")
        columns = {i.column: exp.column(i.column, i.column) for i in inputs}
        values = []
        for m in metrics:
            if m.type == "simple":
                value = columns[m.name]
            elif m.type == "ratio":
                value = exp.Div(this=columns[m.numerator.column],
                                expression=exp.func("NULLIF", columns[m.denominator.column], exp.Literal.number(0)))
            else:
                value = sqlglot.parse_one(m.expr).transform(
                    lambda n: columns[n.name].copy() if isinstance(n, exp.Column) and n.name in columns else n)
            values.append(value.as_(m.name))
        return query.select(*[self._coalesce([i.column for i in inputs], k).as_(k) for k in keys], *values)

    @staticmethod
    def _coalesce(tables: list[str], key: str) -> exp.Expression:
        columns = [exp.column(key, t) for t in tables]
        return columns[0] if len(columns) == 1 else exp.func("COALESCE", *columns)

    @staticmethod
    def _order(query: exp.Select, request: MetricRequest, keys: list[str]) -> exp.Select:
        names = request.order_by or tuple(keys)
        allowed = {*keys, *request.metrics}
        for name in names:
            if name.lstrip("-") not in allowed:
                raise SemanticError(f"can't order by {name.lstrip('-')!r}: it isn't a requested metric or group-by")
        if names:
            query = query.order_by(*[exp.Ordered(this=exp.column(n.lstrip("-")), desc=n.startswith("-"))
                                     for n in names])
        if request.limit is not None:
            if not isinstance(request.limit, int) or isinstance(request.limit, bool) or request.limit < 1:
                raise SemanticError("limit must be a positive whole number")
            query = query.limit(request.limit)
        return query


def _model(document: dict) -> SemanticModel:
    relation = document["node_relation"]
    return SemanticModel(
        name=document["name"], table=f"{relation['schema_name']}.{relation['alias']}",
        description=document.get("description", ""),
        entities={e["name"]: Entity(e["name"], e["type"], e.get("expr", e["name"]))
                  for e in document.get("entities", [])},
        dimensions={d["name"]: Dimension(d["name"], d["type"], d.get("expr", d["name"]),
                                         (d.get("type_params") or {}).get("time_granularity"))
                    for d in document.get("dimensions", [])},
        agg_time_dimension=(document.get("defaults") or {}).get("agg_time_dimension"))


def _input(value: dict) -> MetricInput:
    return MetricInput(value["name"], value.get("alias"), value.get("filter"))


def _metric(document: dict) -> Metric:
    params = document.get("type_params") or {}
    if "measure" in params:
        raise SemanticError(f"metric {document['name']!r} uses a measure; this layer reads measure-free metrics")
    aggregation = params.get("metric_aggregation_params") or {}
    return Metric(
        name=document["name"], type=document["type"], description=document.get("description", ""),
        filter=document.get("filter"), semantic_model=aggregation.get("semantic_model"), expr=params.get("expr"),
        agg=aggregation.get("agg"), agg_time_dimension=aggregation.get("agg_time_dimension"),
        numerator=_input(params["numerator"]) if "numerator" in params else None,
        denominator=_input(params["denominator"]) if "denominator" in params else None,
        inputs=tuple(_input(i) for i in params.get("metrics", ())))


def load(folder: Path = SEMANTIC_DIR) -> SemanticLayer:
    """Read and validate every YAML file in `folder`: semantic models, metrics and one project configuration."""
    models, metrics, configurations = {}, {}, []
    for path in sorted(folder.glob("*.yml")):
        for document in yaml.safe_load_all(path.read_text()):
            if not document:
                continue
            if len(document) != 1:
                raise SemanticError(f"{path.name}: each YAML document has exactly one top-level key")
            (kind, body), = document.items()
            if kind == "semantic_model":
                target, item = models, _model(body)
            elif kind == "metric":
                target, item = metrics, _metric(body)
            elif kind == "project_configuration":
                configurations.append(body)
                continue
            else:
                raise SemanticError(f"{path.name}: unknown document type {kind!r}")
            if item.name in target:
                raise SemanticError(f"{path.name}: {kind} {item.name!r} is defined twice")
            target[item.name] = item
    if len(configurations) != 1:
        raise SemanticError(f"there must be exactly one project_configuration, not {len(configurations)}")
    spines = [s for s in configurations[0].get("time_spines", []) if s["primary_column"]["time_granularity"] == "day"]
    if len(spines) != 1:
        raise SemanticError("there must be exactly one daily time spine")
    relation = spines[0]["node_relation"]
    time_spine = {"table": f"{relation['schema_name']}.{relation['alias']}",
                  "column": spines[0]["primary_column"]["name"],
                  "custom": {g["name"]: g.get("column_name", g["name"]) for g in spines[0].get("custom_granularities", [])}}
    return SemanticLayer(models, metrics, time_spine)
