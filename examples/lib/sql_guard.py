"""Guarded SQL: SQL the agent writes, run on a database that holds only what it may read, checked before it runs,
and run inside limits.

The security boundary is the database, not this module. `warehouse.agent_warehouse()` copies the allowed marts into
a database file of their own, or, given a role's policy, the role's views of them (its rows, with columns masked or
left out), and opens it read-only, with file access, extensions and constant folding off, memory and threads limited,
and its settings locked. A query this module misjudges still can't reach `raw`, `orders_legacy`, another role's rows,
a file or another database, because they aren't there. This module is a teaching layer and defence in depth: it
catches mistakes, gives the model refusals it can repair from, and bounds cost and time. What the database can't hide
are its built-in catalog views and functions, which list its tables and settings, so the parse check below refuses
them.

`check()` parses the agent's SQL with sqlglot and accepts it only if every check passes, in this order:
1. it parses, as one statement, in the warehouse's dialect, and isn't nested too deeply for the parser to follow;
2. it is a query (a `SELECT`, or a `UNION` of them) and nowhere in its tree, CTEs and subqueries included, is there a
   statement that writes, changes settings or reaches outside the warehouse;
3. every table it reads is on the allowlist, named as schema.table, or is a CTE defined in a scope that encloses it;
   no system catalog (`duckdb_*`, `pg_*`, `information_schema`), and nothing but a table or a subquery in FROM, so no
   table function (`read_csv`, `query_table`, `range`, `unnest`) stands in for a table;
4. every function it calls is on `ALLOWED_FUNCTIONS`, the functions the shop's analytics need; a function that reads
   the instance (`current_setting`, `current_database`, `version`) or its catalog is refused by name, and so are the
   pattern operators `SIMILAR TO` and `GLOB`;
5. every column resolves against the allowlisted tables' columns (sqlglot's `qualify`, which also writes each column
   as `"table"."column"`);
6. it returns at most `max_rows` rows: a LIMIT is added, and a smaller one the agent wrote is kept.
A check that fails raises `GuardError`, whose `kind` names the check and whose message is written for the model to
read, so one repair can use it. What runs is the SQL the checks produced (`Checked.sql`), never the agent's text.

`SqlGuard` adds the checks that need the warehouse: before running, `EXPLAIN` estimates how many rows each step of
the plan handles, and a plan with a step over `max_estimated_rows`, or with a step that has no estimate (such as an
`UNNEST`), is refused; its cost is unknown. One deadline of `timeout` seconds covers the whole guard. `EXPLAIN` and
the run happen in a `Worker`: a process of its own, with its own read-only connection to the same database file, which
the guard kills when the deadline passes. DuckDB has no statement timeout, and its `interrupt()` acts only where
DuckDB checks for it, which a heavy step can postpone for many times the limit; a killed process stops at once. The
worker fails closed: out of memory, or dead before it answers, it raises GuardError and returns no rows. The
worker fetches at most `max_rows` + 1 rows and refuses a result of more than `max_result_chars` characters before it
crosses the pipe. `explain()` and `run_with_timeout()` are the in-process versions, with a timer that calls
`interrupt()`, kept to show what that timer can and can't stop.

`answer_with_repair()` runs one question through the guard and, if the guard refuses the SQL or DuckDB raises an
error, gives the model the message once and runs its corrected SQL. `transpile()` writes checked SQL in another
dialect and lists the functions sqlglot passed through without knowing them.
"""
from __future__ import annotations

import atexit
import json
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from multiprocessing.connection import Pipe
from pathlib import Path

import duckdb
import sqlglot
from sqlglot import exp
from sqlglot.errors import ErrorLevel, OptimizeError, ParseError
from sqlglot.optimizer.qualify import qualify

from .answers import Answer, Provenance
from .prompts import repair_messages
from .tools import extract_sql

DIALECT = "duckdb"
MAX_ROWS = 1000
MAX_ESTIMATED_ROWS = 10_000_000       # a rule of thumb for the shop's size: a few hundred times its largest table
TIMEOUT_SECONDS = 5.0
MAX_RESULT_CHARS = 50_000             # about what 1,000 rows of a few short columns print as
MAX_SQL_CHARS = 20_000                # parsing runs in Python, out of the timer's reach, so its input is bounded
NOT_ALLOWED = frozenset({("analytics", "orders_legacy")})    # the old mart with the old revenue definition

# Statements a query must never contain, at its root or anywhere inside it. The root must also be a query, so this
# list is the second line, for statements nested in a CTE or a subquery, where DuckDB accepts a DELETE.
WRITES = (exp.DML, exp.DDL, exp.Drop, exp.Alter, exp.TruncateTable, exp.Command, exp.Pragma, exp.Set, exp.Use,
          exp.Attach, exp.Detach, exp.Install, exp.Transaction, exp.Commit, exp.Rollback, exp.Export, exp.Analyze,
          exp.Kill, exp.LoadData, exp.Summarize, exp.Describe, exp.Show)

# DuckDB's catalog: every database has these schemas, views and table functions, and no setting hides them. They
# list the database's tables, columns and settings, so a query may not read them, whatever it calls them.
CATALOG_SCHEMAS = frozenset({"information_schema", "pg_catalog", "system", "temp", "main"})
CATALOG_PREFIXES = ("duckdb_", "pg_", "sqlite_", "pragma_")
# Functions that read the instance rather than the data: refused by name, so the message says why. sqlglot gives
# some of them names of its own (`version()` is CURRENT_VERSION), so both spellings are listed.
STATE_FUNCTIONS = frozenset({"current_setting", "getvariable", "getenv", "current_database", "current_schema",
                             "current_schemas", "current_catalog", "current_user", "current_role", "session_user",
                             "current_version", "version", "current_query", "txid_current"})
# Every other function must be on this list: what the shop's analytics need, as sqlglot names each function it knows
# (`string_agg` is GROUP_CONCAT, `strftime` TIME_TO_STR, `date_trunc` TIMESTAMP_TRUNC, `quantile_cont`
# PERCENTILE_CONT). Left off: functions that make large values from small ones (`repeat`, `range`, `list_*`), pattern
# matching on arbitrary patterns (`regexp_*`), and anything that reads files or settings or returns random values.
# The operators that match such patterns, which aren't functions, are refused in `PATTERN_OPERATORS`.
PATTERN_OPERATORS = {exp.SimilarTo: "SIMILAR TO", exp.Glob: "GLOB"}    # `~` and RLIKE parse as REGEXP_LIKE
ALLOWED_FUNCTIONS = frozenset({
    # aggregates
    "count", "count_if", "sum", "avg", "min", "max", "median", "mode", "percentile_cont", "percentile_disc",
    "stddev", "stddev_samp", "stddev_pop", "variance", "variance_pop", "corr", "group_concat", "arg_max", "arg_min",
    "any_value", "first", "last", "logical_and", "logical_or", "approx_distinct",
    "histogram",                      # one sqlglot doesn't know, which `transpile()` lists
    # window functions
    "row_number", "rank", "dense_rank", "percent_rank", "cume_dist", "ntile", "lag", "lead", "first_value",
    "last_value", "nth_value",
    # conditions and types
    "case", "if", "coalesce", "nullif", "greatest", "least", "cast", "try_cast", "exists", "array", "struct",
    # numbers
    "round", "floor", "ceil", "abs", "sign", "sqrt", "ln", "pow",
    # dates
    "extract", "date_part", "year", "quarter", "month", "week", "day", "day_of_week", "dayname", "monthname", "date",
    "current_date", "timestamp_trunc", "date_trunc", "datediff", "date_add", "date_sub", "last_day",
    "date_from_parts", "time_to_str",
    # text
    "lower", "upper", "length", "trim", "concat", "substring", "left", "right", "replace", "split_part",
    "starts_with", "contains", "str_position",
})
# Deeper than this, sqlglot's recursive parser and generator can exhaust Python's stack; the shop's queries nest a
# few levels. Checked on the tree, and RecursionError is caught as well.
MAX_DEPTH = 200


class GuardError(ValueError):
    """A check refused the SQL, or the worker stopped it. `kind` names the check: parse, statement, write, table,
    function, column, cost, rows or size; or how the worker stopped: timeout (killed at the deadline), memory (out of
    memory, after which the worker is stopped too) or worker_failed (its process ended, or never started, without an
    answer). Every kind means no rows came back."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class Checked:
    sql: str                          # the SQL that runs: qualified, limited and regenerated by sqlglot
    original: str                     # the agent's SQL, as it wrote it
    tables: tuple[str, ...]           # every table it reads, as schema.table
    limit: int                        # the row limit it runs with


def allowed_schema(con: duckdb.DuckDBPyConnection, schemas: tuple[str, ...] = ("analytics",),
                   exclude: frozenset[tuple[str, str]] = NOT_ALLOWED) -> dict:
    """The allowlist, as sqlglot's schema mapping: {schema: {table: {column: type}}}, read from the warehouse."""
    rows = con.execute(
        """SELECT table_schema, table_name, column_name, data_type FROM information_schema.columns
           WHERE table_schema IN (SELECT unnest($1::VARCHAR[])) ORDER BY table_schema, table_name, ordinal_position""",
        [list(schemas)]).fetchall()
    mapping: dict = {}
    for schema, table, column, data_type in rows:
        if (schema, table) not in exclude:
            mapping.setdefault(schema, {}).setdefault(table, {})[column] = data_type
    return mapping


def _allowed_names(schema: dict) -> list[str]:
    return [f"{db}.{table}" for db, tables in schema.items() for table in tables]


def parse(sql: str, dialect: str = DIALECT) -> exp.Expression:
    """One statement's tree. Raises GuardError("parse") with sqlglot's line and column, or ("statement")."""
    if len(sql) > MAX_SQL_CHARS:
        raise GuardError("statement", f"the SQL is {len(sql):,} characters long, over the limit of {MAX_SQL_CHARS:,}")
    try:
        trees = [t for t in sqlglot.parse(sql, read=dialect, error_level=ErrorLevel.RAISE) if t is not None]
    except ParseError as e:
        first = e.errors[0] if e.errors else {}
        raise GuardError("parse", f"the SQL doesn't parse: {first.get('description', e)} "
                                  f"at line {first.get('line')}, column {first.get('col')}") from None
    except RecursionError:            # sqlglot's parser recurses once per level of nesting
        raise _too_deep() from None
    if len(trees) != 1:
        raise GuardError("statement", f"send one statement, not {len(trees)}")
    if depth(trees[0]) > MAX_DEPTH:
        raise _too_deep()
    return trees[0]


def _too_deep() -> GuardError:
    return GuardError("parse", f"the SQL is nested too deeply to check (the limit is {MAX_DEPTH} levels); "
                               f"write it with fewer nested subqueries and parentheses")


def depth(tree: exp.Expression) -> int:
    """How many levels the tree has, counted without recursion, since recursion is what deep nesting exhausts."""
    deepest, stack = 0, [(tree, 1)]
    while stack:
        node, level = stack.pop()
        deepest = max(deepest, level)
        stack.extend((child, level + 1) for child in node.iter_expressions())
    return deepest


def check_read_only(tree: exp.Expression) -> None:
    """Refuse a root that isn't a query, and any statement that writes, anywhere in the tree."""
    if not isinstance(tree, exp.Query):
        raise GuardError("statement", f"only queries may run, and this is a {type(tree).__name__} statement")
    for node in tree.walk():
        if isinstance(node, WRITES):
            raise GuardError("write", f"the query contains a {type(node).__name__} statement; only reads may run")


def refers_to_cte(table: exp.Table) -> bool:
    """Whether an unqualified table name names a CTE visible where it's used.

    A CTE is visible in the query whose WITH defines it, and in that query's subqueries. Inside the WITH, a CTE sees
    only the CTEs before it (all of them, if the WITH is recursive). A CTE defined in a subquery is invisible outside
    it, so it can't stand in for a table elsewhere in the query.
    """
    if table.db or table.catalog:
        return False
    name = table.name.lower()
    child, node = table, table.parent
    while node is not None:
        if isinstance(node, exp.With):
            names = [cte.alias_or_name.lower() for cte in node.expressions]
            position = next((i for i, cte in enumerate(node.expressions) if cte is child), len(names))
            if name in (names if node.args.get("recursive") else names[:position]):
                return True
            child, node = node.parent, node.parent.parent if node.parent is not None else None
            continue
        if isinstance(node, exp.Query) and node.args.get("with_") is not None:
            if name in {cte.alias_or_name.lower() for cte in node.ctes}:
                return True
        child, node = node, node.parent
    return False


def function_name(function: exp.Func) -> str:
    """The name the function lists use: sqlglot's name for a function it knows, else the name as written."""
    return (function.name if isinstance(function, exp.Anonymous) else function.sql_name()).lower()


def _written(function: exp.Func) -> str:
    """The function's name as DuckDB spells it, for a message; sqlglot's own name if it isn't written as a call."""
    match = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\(", function.sql(DIALECT))
    return (match.group(1) if match else function_name(function)).lower()


def check_functions(tree: exp.Expression, schema: dict, functions: frozenset[str] = ALLOWED_FUNCTIONS) -> None:
    """Refuse every function that reads the instance or its catalog, every other function not in `functions`, and
    the operators that match arbitrary patterns."""
    for operator in tree.find_all(*PATTERN_OPERATORS):
        raise GuardError("function", f"{PATTERN_OPERATORS[type(operator)]} isn't an operator the guard allows; "
                                     f"match text with LIKE, starts_with() or contains()")
    for function in tree.find_all(exp.Func):
        if isinstance(function, exp.Connector):       # AND, OR and XOR are operators, though sqlglot types them so
            continue
        name = function_name(function)
        if name in STATE_FUNCTIONS or name.startswith(CATALOG_PREFIXES):
            raise GuardError("table", f"{_written(function)}() reads the database's settings or catalog; "
                                      f"read only these tables: {', '.join(_allowed_names(schema))}")
        if name not in functions:
            raise GuardError("function", f"{_written(function)}() isn't a function the guard allows; use "
                                         f"aggregates, window functions, casts, and date, number and text functions")


def check_tables(tree: exp.Expression, schema: dict) -> tuple[str, ...]:
    """Every table the query reads, as schema.table. Refuses tables off the allowlist, DuckDB's catalog, and anything
    in FROM that isn't a table or a subquery."""
    allowed = {(db.lower(), table.lower()) for db, tables in schema.items() for table in tables}
    only = f"read only these tables: {', '.join(_allowed_names(schema))}"
    for source in (node.this for node in tree.find_all(exp.From, exp.Join)):
        if not isinstance(source, (exp.Table, exp.Subquery, exp.Values)):
            raise GuardError("table", f"{source.sql(DIALECT)} makes rows from a function, not a table; {only}")
    for function in tree.find_all(exp.Anonymous):      # catalog functions first, so their message names the tables
        if function.name.lower() in STATE_FUNCTIONS or function.name.lower().startswith(CATALOG_PREFIXES):
            raise GuardError("table", f"{function.name}() reads the database's settings or catalog; {only}")
    read = []
    for table in tree.find_all(exp.Table):
        if isinstance(table.this, exp.Func):
            raise GuardError("table", f"{table.this.sql(DIALECT)} reads data through a function; {only}")
        if refers_to_cte(table):
            continue
        db, name = table.db.lower(), table.name.lower()
        shown = f"{table.db}.{table.name}" if table.db else table.name
        if table.catalog:
            raise GuardError("table", f"{table.catalog}.{shown} names a database; {only}")
        if db in CATALOG_SCHEMAS or name.startswith(CATALOG_PREFIXES) or name in CATALOG_SCHEMAS:
            raise GuardError("table", f"{shown} is DuckDB's catalog, not a table you may read; {only}")
        if (db, name) not in allowed:
            raise GuardError("table", f"{shown} isn't a table you may read; "
                                      f"read only these tables, with their schema: {', '.join(_allowed_names(schema))}")
        read.append(f"{db}.{name}")
    return tuple(dict.fromkeys(read))


def bound_rows(tree: exp.Query, max_rows: int) -> tuple[exp.Query, int]:
    """Add a LIMIT of `max_rows` + 1 (one more, so a cut result can be noticed), keeping a smaller LIMIT."""
    current = tree.args.get("limit")
    wanted = max_rows + 1
    if current is not None:
        value = current.expression
        if not (isinstance(value, exp.Literal) and value.is_int):
            raise GuardError("statement", "write LIMIT as a whole number")
        if int(value.this) <= wanted:
            return tree, int(value.this)
    return tree.limit(wanted, copy=False), wanted     # .limit() replaces a LIMIT, so it's called only to lower one


def check(sql: str, schema: dict, max_rows: int = MAX_ROWS, dialect: str = DIALECT,
          functions: frozenset[str] = ALLOWED_FUNCTIONS) -> Checked:
    """Parse and check the agent's SQL against the allowlist `schema`; the SQL to run, or GuardError."""
    tree = parse(sql, dialect)
    check_read_only(tree)
    tables = check_tables(tree, schema)
    check_functions(tree, schema, functions)
    try:
        tree = qualify(tree, schema=schema, dialect=dialect)
        tree, limit = bound_rows(tree, max_rows)
        return Checked(sql=tree.sql(dialect=dialect), original=sql, tables=tables, limit=limit)
    except OptimizeError as e:
        columns = []
        for name in tables:
            db, table = name.split(".")
            columns.append(f"{name} has {', '.join(schema[db][table])}")
        raise GuardError("column", f"{e}. The tables it reads have only these columns: {'; '.join(columns)}") from None
    except RecursionError:            # qualify and the generator recurse too
        raise _too_deep() from None


@dataclass
class Cost:
    largest_estimate: int = 0         # the most rows any step of the plan is estimated to produce
    largest_step: str = ""            # that step's operator, such as HASH_JOIN or CROSS_PRODUCT
    cross_products: int = 0           # how many CROSS_PRODUCT steps the plan has
    unestimated: int = 0              # steps other than a cross product with no estimate: the cost is then unknown
    unestimated_step: str = ""        # the first such step, such as UNNEST


def _estimate(node: dict, cost: Cost) -> int:
    """A step's estimated rows. A cross product, which DuckDB doesn't estimate, gets the product of its inputs'.

    Any other step with no estimate makes the plan's cost unknown: it's counted, and gets its inputs' largest estimate
    only so the walk can go on. `SqlGuard` refuses such a plan rather than trust that number.
    """
    children = [_estimate(child, cost) for child in node.get("children", [])]
    value = (node.get("extra_info") or {}).get("Estimated Cardinality")
    cost.cross_products += node["name"] == "CROSS_PRODUCT"
    if value is not None:
        estimate = int(value)
    elif node["name"] in ("DUMMY_SCAN", "EMPTY_RESULT"):     # a SELECT without FROM reads one row; an empty plan none
        estimate = int(node["name"] == "DUMMY_SCAN")
    elif node["name"] == "CROSS_PRODUCT":
        estimate = 1
        for child in children:
            estimate *= max(child, 1)
    else:
        cost.unestimated += 1
        cost.unestimated_step = cost.unestimated_step or node["name"]
        estimate = max(children, default=0)
    if estimate > cost.largest_estimate:
        cost.largest_estimate, cost.largest_step = estimate, node["name"]
    return estimate


def _interrupt_after(con: duckdb.DuckDBPyConnection, seconds: float | None) -> threading.Timer | None:
    if seconds is None:
        return None
    timer = threading.Timer(seconds, con.interrupt)
    timer.start()
    return timer


def _cost(plan: str) -> Cost:
    cost = Cost()
    for node in json.loads(plan):
        _estimate(node, cost)
    return cost


def explain(con: duckdb.DuckDBPyConnection, sql: str, timeout: float | None = None) -> Cost:
    """The plan's estimated size, from EXPLAIN (FORMAT json), which plans the query without running it.

    Planning can be slow too, so with `timeout` set, a timer interrupts it like a query (GuardError "timeout"). The
    interrupt acts only where DuckDB checks for it; `Worker.explain()` is the version the guard relies on.
    """
    timer = _interrupt_after(con, timeout)
    try:
        (_, plan), = con.execute(f"EXPLAIN (FORMAT json) {sql}").fetchall()
    except duckdb.InterruptException:
        raise GuardError("timeout", f"planning the query ran past the {timeout:g}-second time limit "
                                    f"and was stopped") from None
    finally:
        if timer is not None:
            timer.cancel()
    return _cost(plan)


def run_with_timeout(con: duckdb.DuckDBPyConnection, sql: str, seconds: float,
                     limit: float | None = None) -> tuple[tuple, list]:
    """Run SQL and fetch its rows, interrupting it after `seconds`. Returns (columns, rows); GuardError on timeout.

    `limit` is the time limit the message names, when `seconds` is what remains of it. The interrupt acts only where
    DuckDB checks for it, so a heavy step can run long past `seconds`; `Worker.run()` is what the guard relies on."""
    timer = _interrupt_after(con, seconds)
    seconds = seconds if limit is None else limit
    try:
        result = con.execute(sql)
        columns = tuple(c[0] for c in result.description)
        return columns, result.fetchall()
    except duckdb.InterruptException:
        raise GuardError("timeout", f"the query ran past the {seconds:g}-second time limit and was stopped") from None
    finally:
        timer.cancel()


WORKER = Path(__file__).with_name("guard_worker.py")
# The settings the worker's connection copies from the guard's, so it opens the database with the same protections.
WORKER_SETTINGS = ("enable_external_access", "autoload_known_extensions", "autoinstall_known_extensions",
                   "allow_community_extensions", "allow_persistent_secrets", "secret_directory", "disabled_optimizers",
                   "memory_limit", "threads", "lock_configuration")
STARTUP_SECONDS = 30.0                # opening the database, before any deadline starts
WORKER_HEADROOM = 1536 * 2**20        # bytes the worker may add once its database is open: the 1 GB limit, and more
WORKER_FAILED = ("the query's process ended without an answer, so nothing was returned; "
                 "read fewer rows or build smaller values")


class Worker:
    """A process of its own, with its own read-only connection to the database behind `con` and the same settings,
    that plans and runs SQL and is killed when a deadline passes.

    A killed process stops at once, wherever DuckDB is in its work, which `interrupt()` can't promise. The next
    request starts a new process. Rows come back through a pipe, at most `max_rows` + 1 of them. The worker fails
    closed: if it runs out of memory, or its process dies or never starts, the request raises GuardError ("memory"
    or "worker_failed") and the process is stopped, so no answer comes back and nothing keeps running.
    """

    def __init__(self, con: duckdb.DuckDBPyConnection):
        (self.path,), = con.execute(
            "SELECT path FROM duckdb_databases() WHERE database_name = current_database()").fetchall()
        self.settings = {name: con.execute("SELECT current_setting(?)", [name]).fetchone()[0]
                         for name in WORKER_SETTINGS}
        self.process: subprocess.Popen | None = None
        self.pipe = None
        atexit.register(self.stop)

    def start(self) -> None:
        """Start the process, if it isn't running, and wait until its connection is open."""
        if self.process is not None and self.process.poll() is None:
            return
        ours, theirs = Pipe()
        try:
            self.process = subprocess.Popen(
                [sys.executable, "-I", str(WORKER), str(theirs.fileno()), self.path, json.dumps(self.settings),
                 str(WORKER_HEADROOM)], pass_fds=(theirs.fileno(),))
        except OSError:
            ours.close()
            raise GuardError("worker_failed", WORKER_FAILED) from None
        finally:
            theirs.close()
        self.pipe = ours
        try:
            ready = ours.poll(STARTUP_SECONDS) and ours.recv() == ("ready",)
        except (EOFError, OSError):
            ready = False
        if not ready:                                     # it died, or didn't open the database in time
            self.stop()
            raise GuardError("worker_failed", WORKER_FAILED)

    @property
    def running(self) -> bool:
        """Whether the worker's process is alive."""
        return self.process is not None and self.process.poll() is None

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.kill()
            self.process.wait()
        if self.pipe is not None:
            self.pipe.close()
        self.process = self.pipe = None

    def _ask(self, request: tuple, seconds: float, message: str) -> tuple:
        self.start()
        try:
            self.pipe.send(request)
            answered = self.pipe.poll(max(seconds, 0))
            reply = self.pipe.recv() if answered else None
        except (EOFError, OSError):                       # the process died, for example killed by the system
            self.stop()
            raise GuardError("worker_failed", WORKER_FAILED) from None
        if not answered:
            self.stop()                                   # the deadline: kill the process, whatever it's doing
            raise GuardError("timeout", message)
        if reply[0] == "error" and reply[1] == "OutOfMemoryException":
            self.stop()                                   # a fresh process for the next request
            raise GuardError("memory", "the query ran out of memory and was stopped; read fewer rows or build "
                                       "smaller values")
        if reply[0] == "error":
            error = getattr(duckdb, reply[1], duckdb.Error)
            raise (error if isinstance(error, type) and issubclass(error, duckdb.Error) else duckdb.Error)(reply[2])
        return reply

    def explain(self, sql: str, seconds: float, limit: float | None = None) -> Cost:
        """The plan's estimated size, like `explain()`, killed after `seconds` (GuardError "timeout")."""
        _, plan = self._ask(("explain", sql), seconds, f"planning the query ran past the "
                                                      f"{seconds if limit is None else limit:g}-second time limit "
                                                      f"and was stopped")
        return _cost(plan)

    def run(self, sql: str, seconds: float, max_rows: int = MAX_ROWS, max_chars: int = MAX_RESULT_CHARS,
            limit: float | None = None) -> tuple[tuple, list]:
        """Run SQL, like `run_with_timeout()`, killed after `seconds`. Returns (columns, rows), or GuardError for a
        timeout, more than `max_rows` rows or more than `max_chars` characters."""
        reply = self._ask(("run", sql, max_rows, max_chars), seconds,
                          f"the query ran past the {seconds if limit is None else limit:g}-second time limit "
                          f"and was stopped")
        if reply[0] == "rows":
            raise GuardError("rows", f"the query returns more than {max_rows} rows; aggregate or filter it")
        if reply[0] == "size":
            raise GuardError("size", f"the result is {reply[1]:,} characters long, over the limit of "
                                     f"{max_chars:,}; return fewer or shorter values")
        _, columns, rows = reply
        return columns, rows


@dataclass
class SqlGuard:
    """The guard for one warehouse: the allowlist of tables and functions, the row and size bounds, the plan's size
    limit and the time limit.

    Give it the agent's own connection, `warehouse.agent_warehouse()`, or a role's (`policy=`), so the database holds
    only what it may read.
    `EXPLAIN` and the run happen in a `Worker` on the same database file, started before the deadline does.
    """
    con: duckdb.DuckDBPyConnection
    schema: dict = field(default_factory=dict)
    max_rows: int = MAX_ROWS
    max_estimated_rows: int = MAX_ESTIMATED_ROWS
    timeout: float = TIMEOUT_SECONDS
    max_result_chars: int = MAX_RESULT_CHARS
    functions: frozenset[str] = ALLOWED_FUNCTIONS
    _worker: Worker | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self):
        if not self.schema:
            self.schema = allowed_schema(self.con)

    @property
    def worker(self) -> Worker:
        """The guard's worker, running and ready; a subclass's `__post_init__` needn't create it."""
        if self._worker is None:
            self._worker = Worker(self.con)
        self._worker.start()
        return self._worker

    @property
    def worker_running(self) -> bool:
        """Whether the guard's worker process is alive, without starting one."""
        return self._worker is not None and self._worker.running

    def _remaining(self, deadline: float) -> float:
        left = deadline - time.monotonic()
        if left <= 0:
            raise GuardError("timeout", f"checking the query ran past the {self.timeout:g}-second time limit")
        return left

    def _check(self, sql: str, deadline: float) -> Checked:
        checked = check(sql, self.schema, self.max_rows, functions=self.functions)
        cost = self.worker.explain(checked.sql, self._remaining(deadline), limit=self.timeout)
        if cost.unestimated:
            raise GuardError("cost", f"a step of the plan ({cost.unestimated_step}) has no estimate, so the query's "
                                     f"cost is unknown; read rows from the allowed tables, not from a function")
        if cost.largest_estimate > self.max_estimated_rows:
            hint = "; join each table on its key" if cost.largest_step == "CROSS_PRODUCT" else ""
            raise GuardError("cost", f"one step of the plan ({cost.largest_step}) is estimated to produce "
                                     f"{cost.largest_estimate:,} rows, over the limit of "
                                     f"{self.max_estimated_rows:,}{hint}")
        return checked

    def check(self, sql: str) -> Checked:
        """`check()`, then the plan: refuse a plan with a step estimated over `max_estimated_rows` rows, or with a
        step that has no estimate. The parse checks and `EXPLAIN` share one deadline of `timeout` seconds."""
        self.worker                       # started before the deadline: opening the database isn't the query's time
        return self._check(sql, time.monotonic() + self.timeout)

    def run(self, sql: str, role: str = "analyst") -> Answer:
        """Check the SQL and run what the checks produced, all within one deadline; an answer, or GuardError."""
        self.worker                       # started, or restarted after a kill, before the deadline starts
        deadline = time.monotonic() + self.timeout
        checked = self.check(sql)         # self.check, so a subclass's check (chapter 9's policy) is what runs
        columns, rows = self.worker.run(checked.sql, self._remaining(deadline), self.max_rows,
                                        self.max_result_chars, limit=self.timeout)
        return Answer(columns=columns, rows=tuple(rows), provenance=Provenance(source="sql", sql=checked.sql, role=role))


@dataclass
class Attempt:
    sql: str
    outcome: str                      # "ran", or the GuardError kind, or "error" for a DuckDB error
    message: str = ""


@dataclass
class GuardedRun:
    question: str
    attempts: list[Attempt] = field(default_factory=list)
    answer: Answer | None = None

    @property
    def repaired(self) -> bool:
        return len(self.attempts) > 1


def _attempt(guard: SqlGuard, reply: str, role: str) -> tuple[Attempt, Answer | None]:
    sql = extract_sql(reply)
    if sql.lower().startswith("cannot answer"):
        return Attempt(sql, "declined", sql), Answer.decline(sql.split(":", 1)[-1].strip(), role=role)
    try:
        answer = guard.run(sql, role)
    except GuardError as e:
        return Attempt(sql, e.kind, str(e)), None
    except duckdb.Error as e:
        return Attempt(sql, "error", str(e).strip()[:600]), None
    return Attempt(sql, "ran"), answer


def answer_with_repair(guard: SqlGuard, model, messages: list[dict], question: str, role: str = "analyst",
                       repairs: int = 1) -> GuardedRun:
    """Ask for SQL, run it through the guard and, if it's refused or fails, repair it at most `repairs` times."""
    run = GuardedRun(question)
    for _ in range(repairs + 1):
        reply = model.complete(messages)
        attempt, answer = _attempt(guard, reply, role)
        run.attempts.append(attempt)
        if answer is not None:
            run.answer = answer
            return run
        messages = repair_messages(messages, reply, attempt.message)
    run.answer = Answer.decline(f"the SQL was refused or failed: {run.attempts[-1].message}", role=role)
    return run


@dataclass(frozen=True)
class Transpiled:
    sql: str
    passed_through: tuple[str, ...]   # functions sqlglot doesn't know, written out unchanged


def transpile(sql: str, dialect: str, read: str = DIALECT, pretty: bool = False, quoted: bool = False) -> Transpiled:
    """Write SQL in another dialect, raising on what sqlglot knows it can't translate (`UnsupportedError`).

    `check()` quotes every identifier, which DuckDB ignores for case. Some warehouses don't: Snowflake stores unquoted
    names in upper case and matches quoted ones exactly. So the quotes are dropped unless `quoted` is set.
    """
    tree = sqlglot.parse_one(sql, read=read)
    if not quoted:
        for identifier in tree.find_all(exp.Identifier):
            identifier.set("quoted", False)
    unknown = tuple(dict.fromkeys(f.name.lower() for f in tree.find_all(exp.Anonymous)))
    return Transpiled(tree.sql(dialect=dialect, unsupported_level=ErrorLevel.RAISE, pretty=pretty), unknown)
