"""Who may see what: each role's tables, row filters, column masks and minimum group size, applied below the agent.

`policy_for(role, region)` reads `examples/data/shop/roles.toml` into a `Policy`. The rules are enforced on the SQL
that runs, never in a prompt, so nothing the model writes, and nothing a question or a row of data tells it, can
widen them. Both of the agent's paths go through the same rewrite, `Policy.apply()`:

- **Replace each table.** Every table a query reads, by its schema and name, becomes a subquery under the query's
  own alias for it: the table's columns in order, a masked column as the mask's constant, a denied column left out,
  and a `WHERE` with the role's row filter. Whatever the query then does, in its `WHERE`, joins or aggregates, it
  does to that subquery, so a filter on a masked email matches nothing and a lead's sum covers their region only.
  A table the role isn't given, `raw` included, is refused: deny by default.
- **Metrics:** `PolicyLayer` is the semantic layer for one role. It hides the metrics that read a denied column and
  the dimensions on one, refuses a request that names them or filters on a value the role's rows don't hold (another
  region, or a country in one), and passes every compiled query through `apply()`; an answer's provenance says
  which row filter applied. For a role with a minimum group size, it also counts the distinct
  customers behind each group of an answer, with the same filters, and suppresses the values of any group with
  fewer. A metric whose rows don't name their customer can't be checked that way, so such a role doesn't get it.
- **Guarded SQL:** `PolicyGuard` is chapter 7's `SqlGuard` with the role's allowlist (its tables, without denied
  columns, so refusals don't name them either) and `apply()` on the SQL the checks produced; the rewritten SQL then
  goes through the guard's checks again, cost included, and only SQL the policy produced may run. Give it the role's
  own database, `warehouse.agent_warehouse(con, policy=policy)`, which holds only the role's views of the marts: that
  database is the boundary, and the rewrite is defence in depth and the place each rule is written once. A role with
  a minimum group size gets no guarded SQL, because the guard can't count the people behind an arbitrary query's groups.
- `PolicyToolbox` is chapter 6's metrics-first toolbox over a `PolicyLayer`: a request the policy refuses ends the
  run with a decline whose reason starts "forbidden", decided by code, not by the model.

`AuditLog` records who asked what and what ran: one entry per answer, with the SQL after the policy.

Suppressing small groups protects each answer on its own. It doesn't stop someone from subtracting two answers that
are each safe, which recovers a suppressed group: chapter 9 shows this, and why the limit holds.

Policy as code in general, with Rego and Cedar, is the subject of the book *Data Governance as Code*.
"""
from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

import duckdb
import sqlglot
from sqlglot import exp

from .answers import Answer, Provenance
from .metric_tools import MetricToolbox
from .semantic import Metric, MetricRequest, SemanticLayer
from .sql_guard import Checked, GuardError, SqlGuard
from .tools import ToolResult

ROLES = Path(__file__).resolve().parent.parent / "data" / "shop" / "roles.toml"


class PolicyError(Exception):
    """The role may not see what was asked. Not a ValueError, so a tool's ordinary error handling can't swallow it."""


@dataclass(frozen=True)
class Policy:
    role: str
    region: str | None = None
    tables: tuple[str, ...] = ()                  # schema.table the role may read
    deny: dict = field(default_factory=dict)      # schema.table -> columns left out
    mask: dict = field(default_factory=dict)      # schema.table -> columns shown as `mask_value`
    row_filters: dict = field(default_factory=dict)   # schema.table -> SQL condition with :region
    unfiltered: tuple[str, ...] = ()              # tables a filtered role reads whole
    filtered: bool = False                        # whether the role has a row filter
    minimum_group_size: int | None = None
    guarded_sql: bool = True
    mask_value: str = "'(masked)'"

    def describe(self) -> str:
        lines = [f"role: {self.role}" + (f" ({self.region})" if self.region else "")]
        for table in self.tables:
            notes = []
            if self.filtered:
                notes.append(f"rows where {self.condition(table).sql('duckdb')}" if table in self.row_filters
                             else "every row")
            if self.mask.get(table):
                notes.append(f"masks {', '.join(self.mask[table])}")
            if self.deny.get(table):
                notes.append(f"denies {', '.join(self.deny[table])}")
            lines.append(f"  {table}" + (f": {'; '.join(notes)}" if notes else ""))
        if self.minimum_group_size:
            lines.append(f"  minimum group size: {self.minimum_group_size} customers")
        return "\n".join(lines)

    # The rules for one table ---------------------------------------------------------------------------------

    def check_table(self, table: str) -> None:
        if table not in self.tables:
            raise PolicyError(f"the {self.role} role may not read {table}")
        if self.filtered and table not in self.row_filters and table not in self.unfiltered:
            raise PolicyError(f"no row filter says which rows of {table} the {self.role} role may read")

    def condition(self, table: str) -> exp.Expression | None:
        """The table's row filter, with :region bound as a SQL literal, or None if the role reads every row."""
        if not self.filtered or table not in self.row_filters:
            return None
        tree = sqlglot.parse_one(self.row_filters[table], dialect="duckdb")
        return tree.transform(lambda n: exp.Literal.string(self.region)
                              if isinstance(n, exp.Placeholder) and n.name == "region" else n)

    def subquery(self, table: str, columns: list[str]) -> exp.Select:
        """What the role sees of `table`: its columns, masked or left out, and the rows its filter keeps."""
        self.check_table(table)
        masked, denied = set(self.mask.get(table, ())), set(self.deny.get(table, ()))
        mask = sqlglot.parse_one(self.mask_value, dialect="duckdb")
        selected = [mask.copy().as_(c, quoted=True) if c in masked else exp.column(c, quoted=True)
                    for c in columns if c not in denied]
        query = exp.select(*selected).from_(exp.to_table(table))
        condition = self.condition(table)
        return query.where(condition) if condition is not None else query

    # The rewrite both paths go through ---------------------------------------------------------------------

    def apply(self, tree: exp.Expression, columns: dict[str, list[str]]) -> exp.Expression:
        """Replace each table the query reads with the role's subquery, under the query's alias for it.

        `columns` maps schema.table to its columns in order (`table_columns()`). A table with no schema is a CTE's
        name and stays as it is. Raises PolicyError for a table the role may not read."""
        tree = tree.copy()
        for table in list(tree.find_all(exp.Table)):
            if not table.db:
                continue
            name = f"{table.db}.{table.name}"
            if name not in columns:
                raise PolicyError(f"the {self.role} role may not read {name}")
            alias = table.args.get("alias")
            alias = alias.copy() if alias is not None else exp.TableAlias(this=exp.to_identifier(table.name))
            table.replace(exp.Subquery(this=self.subquery(name, columns[name]), alias=alias))
        return tree

    def allowed_schema(self, con: duckdb.DuckDBPyConnection, schemas: tuple[str, ...] = ("analytics",)) -> dict:
        """The guard's allowlist for this role: its tables in `schemas`, with their columns, less denied ones."""
        mapping: dict = {}
        for name, columns in table_columns(con, schemas).items():
            if name in self.tables:
                db, table = name.split(".")
                try:
                    self.check_table(name)
                except PolicyError:
                    continue
                denied = set(self.deny.get(name, ()))
                mapping.setdefault(db, {})[table] = {c: t for c, t in columns.items() if c not in denied}
        return mapping


def table_columns(con: duckdb.DuckDBPyConnection, schemas: tuple[str, ...] = ("analytics", "semantic")) -> dict:
    """{schema.table: {column: type}} for every table and view in `schemas`, columns in order."""
    rows = con.execute(
        """SELECT table_schema || '.' || table_name, column_name, data_type FROM information_schema.columns
           WHERE table_schema IN (SELECT unnest($1::VARCHAR[])) ORDER BY table_schema, table_name, ordinal_position""",
        [list(schemas)]).fetchall()
    mapping: dict = {}
    for table, column, data_type in rows:
        mapping.setdefault(table, {})[column] = data_type
    return mapping


def load_roles(path: Path = ROLES) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def policy_for(role: str, region: str | None = None, path: Path = ROLES) -> Policy:
    """The policy for one role; a regional lead needs their region. Raises PolicyError for an unknown role."""
    config = load_roles(path)
    if role not in config["roles"]:
        raise PolicyError(f"unknown role {role!r}; roles: {', '.join(config['roles'])}")
    entry = config["roles"][role]
    filters = config.get("row_filters", {}).get(entry.get("row_filter", ""), {})
    if entry.get("row_filter") and not region:
        raise PolicyError(f"the {role} role needs a region")
    return Policy(
        role=role, region=region if entry.get("row_filter") else None,
        tables=tuple(entry.get("tables", config["tables"])),
        deny={t: tuple(c) for t, c in entry.get("deny", {}).items()},
        mask={t: tuple(c) for t, c in entry.get("mask", {}).items()},
        row_filters={t: c for t, c in filters.items() if t != "unfiltered"},
        unfiltered=tuple(filters.get("unfiltered", ())), filtered=bool(entry.get("row_filter")),
        minimum_group_size=entry.get("minimum_group_size"), guarded_sql=entry.get("guarded_sql", True),
        mask_value=config.get("mask", "'(masked)'"))


# The semantic layer, for one role ---------------------------------------------------------------------------

def _reads(layer: SemanticLayer, metric: Metric) -> list[tuple[str, str]]:
    """(table, column) pairs a metric's expression reads, through every simple metric it is built from."""
    pairs = []
    for i in layer.simple_metrics_for(metric.name):
        simple = layer.metrics[i.name]
        table = layer.semantic_models[simple.semantic_model].table
        pairs += [(table, c.name) for c in sqlglot.parse_one(simple.expr).find_all(exp.Column)]
    return pairs


class PolicyLayer(SemanticLayer):
    """The semantic layer as one role sees it: fewer metrics and dimensions, and every query rewritten."""

    def __init__(self, layer: SemanticLayer, policy: Policy, con: duckdb.DuckDBPyConnection):
        self.base, self.policy, self.con, self.columns = layer, policy, con, table_columns(con)
        self.denied_metrics = {name for name, m in layer.metrics.items()
                               if any(c in policy.deny.get(t, ()) or t not in policy.tables
                                      for t, c in _reads(layer, m))
                               or (policy.minimum_group_size and not self._traceable(layer, m))}
        self.suppressed = 0                   # groups the last query suppressed
        super().__init__(layer.semantic_models, {n: m for n, m in layer.metrics.items()
                                                  if n not in self.denied_metrics}, layer.time_spine)

    @staticmethod
    def _traceable(layer: SemanticLayer, metric: Metric) -> bool:
        """Whether every row the metric reads names its customer, so a group's customers can be counted."""
        return all("customer" in layer.semantic_models[layer.metrics[i.name].semantic_model].entities
                   for i in layer.simple_metrics_for(metric.name))

    def _denied_dimension(self, name: str) -> bool:
        parts = name.split("__")
        if parts[0] == "metric_time" or len(parts) < 2:
            return False
        model = self._owner(parts[-2])
        dimension = model.dimensions.get(parts[-1]) if model else None
        if dimension is None:
            return False
        read = {c.name for c in sqlglot.parse_one(dimension.expr).find_all(exp.Column)}
        return model.table not in self.policy.tables or bool(read & set(self.policy.deny.get(model.table, ())))

    def dimensions_for(self, name: str) -> list[str]:
        return [d for d in super().dimensions_for(name) if not self._denied_dimension(d)]

    def check_request(self, request: MetricRequest) -> None:
        """Refuse what the role may not ask for: a denied metric or dimension, or a region that isn't theirs."""
        for name in request.metrics:
            if name in self.denied_metrics:
                raise PolicyError(f"the {self.policy.role} role may not see {name}")
        for name in [*request.group_by, *request.filters]:
            if self._denied_dimension(name):
                raise PolicyError(f"the {self.policy.role} role may not see {name}")
        if self.policy.filtered:
            for name, value in request.filters.items():
                hidden = self.hidden_values(name, value if isinstance(value, (list, tuple)) else [value])
                if hidden:
                    shown = ", ".join(map(repr, hidden))
                    raise PolicyError(f"the {self.policy.role} role for {self.policy.region} may not see rows where "
                                      f"{name} is {shown}")

    def hidden_values(self, name: str, values: list) -> list:
        """Filter values that rows of the warehouse hold but the role's rows don't: asking for them is forbidden,
        not a question whose answer is empty."""
        parts = name.split("__")
        model = self._owner(parts[-2]) if parts[0] != "metric_time" and len(parts) > 1 else None
        dimension = model.dimensions.get(parts[-1]) if model else None
        if dimension is None or dimension.type != "categorical":
            return []
        seen = lambda source: {row[0] for row in self.con.execute(
            f"SELECT DISTINCT {dimension.expr} FROM {source} AS t").fetchall()}
        everyone = self.held_anywhere(model.table, dimension.expr)
        theirs = seen(f"({self.policy.subquery(model.table, list(self.columns[model.table])).sql('duckdb')})")
        return [v for v in values if v in everyone and v not in theirs]

    def held_anywhere(self, table: str, expr: str) -> set:
        """Every value of a dimension's expression in `table`, whoever may see the rows that hold it."""
        return {row[0] for row in self.con.execute(f"SELECT DISTINCT {expr} FROM {table} AS t").fetchall()}

    def compile(self, request: MetricRequest) -> exp.Select:
        self.check_request(request)
        return self.policy.apply(super().compile(request), self.columns)

    def query(self, con: duckdb.DuckDBPyConnection, request: MetricRequest, role: str = "analyst") -> Answer:
        answer = super().query(con, request, role=self.policy.role)
        if self.policy.filtered:       # the answer says that the role's filter applied, not only the request's
            answer = replace(answer, provenance=replace(answer.provenance, filters={
                **answer.provenance.filters, "row filter": f"{self.policy.region} only"}))
        self.suppressed = 0
        if not self.policy.minimum_group_size:
            return answer
        counts = self.people_counts(con, request)
        keys = [answer.columns.index(k) for k in request.group_by]
        values = [i for i, c in enumerate(answer.columns) if c not in request.group_by]
        rows = []
        for row in answer.rows:
            if counts.get(tuple(row[k] for k in keys), 0) < self.policy.minimum_group_size:
                self.suppressed += 1
                row = tuple(f"(under {self.policy.minimum_group_size})" if i in values else v
                            for i, v in enumerate(row))
            rows.append(row)
        return replace(answer, rows=tuple(rows))

    def people_counts(self, con: duckdb.DuckDBPyConnection, request: MetricRequest) -> dict:
        """For each group of a request, the fewest distinct customers behind any metric it reads, with its filters."""
        counts: dict = {}
        for i in {i for m in request.metrics for i in self.simple_metrics_for(m)}:
            metric = self.metrics[i.name]
            model = self.semantic_models[metric.semantic_model]
            customer = model.entities.get("customer")
            if customer is None:
                raise PolicyError(f"{i.name} can't be traced to customers, so its groups can't be checked against "
                                  f"the minimum group size of {self.policy.minimum_group_size}")
            condition = " AND ".join(f"({f})" for f in (metric.filter, i.filter) if f) or None
            people = Metric(name="customers_behind", type="simple", semantic_model=model.name, expr=customer.expr,
                            agg="count_distinct", agg_time_dimension=metric.agg_time_dimension, filter=condition)
            layer = SemanticLayer(self.semantic_models, {**self.metrics, people.name: people}, self.time_spine)
            sql = self.policy.apply(layer.compile(MetricRequest((people.name,), request.group_by,
                                                                request.filters)), self.columns)
            for *key, n in con.execute(sql.sql(dialect="duckdb")).fetchall():
                counts[tuple(key)] = min(n, counts.get(tuple(key), n))
        return counts


class PolicyToolbox(MetricToolbox):
    """Chapter 6's metrics-first tools for one role: a request the policy refuses ends the run with a decline."""

    def __init__(self, con: duckdb.DuckDBPyConnection, layer: PolicyLayer):
        super().__init__(con, layer, role=layer.policy.role)

    def query_metric(self, arguments: dict) -> ToolResult:
        try:
            if isinstance(arguments.get("metrics", arguments.get("metric")), (str, list)):
                listed = {k: [v] if k in ("metrics", "group_by", "order_by") and isinstance(v, str) else v
                          for k, v in arguments.items()}
                self.layer.check_request(MetricRequest.from_arguments(listed))
            return super().query_metric(arguments)
        except PolicyError as e:
            reason = f"forbidden: {e}"
            return ToolResult(f"declined: {reason}", Answer.decline(reason, role=self.role))


# Guarded SQL, for one role ---------------------------------------------------------------------------------

@dataclass
class PolicyGuard(SqlGuard):
    """Chapter 7's guard with one role's allowlist, and the role's rewrite on the SQL that runs.

    Run it on the role's own database, `agent_warehouse(con, policy=policy)`, so a query the rewrite misjudges still
    reads only the role's rows and columns."""
    policy: Policy | None = None

    def __post_init__(self):
        if self.policy is None:
            raise ValueError("PolicyGuard needs a policy")
        if not self.schema:
            self.schema = self.policy.allowed_schema(self.con)
        self.columns = table_columns(self.con)
        self.rewritten: set[str] = set()      # every SQL text the policy produced, to check what ran

    def check(self, sql: str) -> Checked:
        if not self.policy.guarded_sql:
            raise GuardError("policy", f"the {self.policy.role} role can't run SQL; ask for a metric")
        checked = super().check(sql)
        try:
            tree = self.policy.apply(sqlglot.parse_one(checked.sql, read="duckdb"), self.columns)
        except PolicyError as e:
            raise GuardError("policy", str(e)) from None
        # The rewrite goes through every check again, EXPLAIN's cost limit included, so what is checked is what runs.
        final = super().check(tree.sql(dialect="duckdb"))
        self.rewritten.add(final.sql)
        return replace(checked, sql=final.sql)

    def run(self, sql: str, role: str = "analyst") -> Answer:
        answer = super().run(sql, role=self.policy.role)
        # Fail closed: the SQL that ran must be the policy's rewrite, whatever the guard underneath does to run it.
        if answer.provenance.sql not in self.rewritten:
            raise GuardError("policy", "the query ran without the role's policy applied")
        return answer


# Who asked what, and what ran ------------------------------------------------------------------------------

@dataclass
class AuditLog:
    """One entry per question: who asked, as which role, what the agent asked for, the SQL that ran, and the outcome.

    `principal` is whatever identifies the person in your sign-in system; the book uses made-up IDs."""
    entries: list[dict] = field(default_factory=list)

    def record(self, principal: str, policy: Policy, question: str, answer: Answer, request: dict | None = None,
               agent_sql: str | None = None, suppressed: int = 0) -> dict:
        provenance = answer.provenance
        ran = provenance.sql if provenance else ""
        tables = sorted({f"{t.db}.{t.name}" for t in sqlglot.parse_one(ran, read="duckdb").find_all(exp.Table)
                         if t.db}) if ran else []
        entry = {"entry": len(self.entries) + 1, "principal": principal, "role": policy.role,
                 "region": policy.region, "question": question,
                 "path": provenance.source if provenance else "none",
                 "request": request, "agent_sql": agent_sql,
                 "filters": provenance.filters if provenance and answer.answered else {},
                 "sql_sha256": hashlib.sha256(ran.encode()).hexdigest()[:16] if ran else None,
                 "sql": ran or None,            # the SQL that ran, after the policy; the hash is its short key
                 "tables": tables,
                 "masked": [f"{t}.{c}" for t in tables for c in policy.mask.get(t, ())],
                 "outcome": "answered" if answer.answered else "declined",
                 "rows": len(answer.rows), "suppressed_groups": suppressed,
                 "reason": answer.reason, "data_as_of": provenance.data_as_of if provenance else None}
        self.entries.append(entry)
        return entry

    def jsonl(self) -> str:
        return "\n".join(json.dumps(e, ensure_ascii=False) for e in self.entries)
