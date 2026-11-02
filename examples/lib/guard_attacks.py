"""Attempts to get past chapter 7's guard, kept as a test: each was found by a critic against a draft of the
guard, and each must now be refused, except the last, which shows what the plan's estimate misses. They run only
against the agent's database. `macro_then_sum()` shows whether a temporary macro outlasts its request.

`ATTEMPTS` maps a label to the SQL. `ALONE` describes, for some of them, what the agent's database returns with no
guard in front, from its rows. `alone()` and `attempt()` run one attempt each way.
"""
import duckdb

from .sql_guard import TIMEOUT_SECONDS, GuardError
ATTEMPTS = {
    # A CTE whose name matches a catalog view, defined in a subquery, let the view through everywhere.
    "CTE named duckdb_tables": """SELECT * FROM (WITH duckdb_tables AS (SELECT 1 AS x) SELECT x FROM duckdb_tables) AS a,
duckdb_tables""",
    "CTE named pg_settings": """SELECT * FROM (WITH pg_settings AS (SELECT 1 AS x) SELECT x FROM pg_settings) AS a,
pg_settings""",
    # A constant that DuckDB folds while it plans, where no timer reached.
    "slow plan": """SELECT count(*) AS n FROM analytics.fct_orders
WHERE order_id < list_sum(list_transform(range(30000000), x -> list_sum(range(40))))""",
    # A cross product with rows made by a function, which has no estimate.
    "unnest in FROM": "SELECT count(*) AS n FROM analytics.fct_orders AS o, unnest(range(200000)) AS t(x)",
    "unnest in a subquery": """SELECT count(*) AS n FROM analytics.fct_orders AS o,
(SELECT unnest(range(200000)) AS x) AS t""",
    # One row that holds every customer's name and email.
    "every email in one row": "SELECT string_agg(email || ' ' || customer_name, ',') AS s FROM analytics.dim_customers",
    # A function that reads a setting, and a table named with its database.
    "a setting read by a function": "SELECT current_setting('temp_directory') AS t",
    "a table named with its database": "SELECT count(*) AS n FROM agent.analytics.fct_orders",
    # Found by the security review. Heavy string work on an allowed table, which DuckDB checks for an interrupt only
    # between batches of rows: one batch of these strings is gigabytes of text, so a timer can't stop it in time.
    "regex on a repeated email": """SELECT count(*) AS n FROM analytics.dim_customers
WHERE regexp_matches(repeat(email, 200000), '(a|b|c|d)*z$')""",
    # Functions that read the instance, which sqlglot parses into nodes of their own.
    "database name and version": "SELECT current_database() AS db, version() AS v",
    # Nesting deep enough to exhaust the parser's recursion, under the 20,000-character limit.
    "600 nested subqueries": "SELECT x FROM " + "".join("(SELECT x FROM " for _ in range(599))
                             + "(SELECT 1 AS x) AS t" + "".join(f") AS t{i}" for i in range(599)),
    # Found by the final security review: a regular expression written as an operator, which no function list sees.
    "SIMILAR TO on an email": """SELECT count(*) AS n FROM analytics.dim_customers
WHERE email SIMILAR TO '(a|b|c)*z'""",
    # Also found by the final review. A read-only connection accepts a temporary macro, and every later sum() on
    # that connection returns 42.
    "temp macro named sum": "CREATE TEMP MACRO sum(x) AS 42",
    # A join whose plan is estimated far below what it produces.
    "join on inequality": """SELECT count(*) AS n FROM analytics.fct_orders AS o
JOIN analytics.dim_customers AS c ON o.customer_id <> c.customer_id""",
}

ALONE = {
    "CTE named duckdb_tables": lambda rows: f"{len(rows)} rows, one per table, all in analytics: "
                                            f"{all('analytics' in row for row in rows)}",
    "CTE named pg_settings": lambda rows: f"{len(rows)} rows of settings",
    "every email in one row": lambda rows: f"{len(rows)} row of {len(rows[0][0]):,} characters",
    "a setting read by a function": lambda rows: f"{len(rows)} row, a folder's path",
    "a table named with its database": lambda rows: f"{rows[0][0]:,} orders",
    "database name and version": lambda rows: f"{rows[0][0]}, {rows[0][1]}",
}


NEXT_SUM = "SELECT sum(net_revenue_eur) AS s FROM analytics.fct_orders"


def macro_then_sum(con: duckdb.DuckDBPyConnection, worker) -> tuple:
    """The temporary macro named sum, then `NEXT_SUM`: first on a cursor of the database behind `con` alone, then
    straight to `worker`, a guard's `Worker`, as if the parser had let the macro through. Returns the first sum, and
    whether the worker's sum is the real one."""
    cursor = con.cursor()
    cursor.execute(ATTEMPTS["temp macro named sum"])
    alone_sum = cursor.execute(NEXT_SUM).fetchone()[0]
    worker.run(ATTEMPTS["temp macro named sum"], seconds=TIMEOUT_SECONDS)
    return alone_sum, worker.run(NEXT_SUM, seconds=TIMEOUT_SECONDS)[1] == con.execute(NEXT_SUM).fetchall()


def alone(con: duckdb.DuckDBPyConnection, label: str) -> str:
    """What the database behind `con` returns for an attempt, with no guard in front, or its error's first line."""
    try:
        return ALONE[label](con.execute(ATTEMPTS[label]).fetchall())
    except duckdb.Error as e:
        return str(e).splitlines()[0]


# How the guard ended an attempt: no rows came back from anything but "ran". The worker's three ways of stopping a
# query are one outcome, because which one happens first (the deadline, the memory cap, or the system ending the
# process) depends on the machine.
STOPPED = frozenset({"timeout", "memory", "worker_failed"})


def outcome_category(kind: str) -> str:
    """"ran", "refused" for a check, "stopped, no answer" for the worker's ways of stopping, or "error"."""
    return kind if kind in ("ran", "error") else "stopped, no answer" if kind in STOPPED else "refused"


def attempt(run, sql: str) -> tuple[str, str]:
    """Pass `sql` to `run`, such as a guard's `run()`. Returns "ran", or the refusal's kind and first clause, or
    DuckDB's error; and its category, `outcome_category()`. Nothing it raises escapes but a bug."""
    try:
        run(sql)
        return "ran", "ran"
    except GuardError as e:
        return f"refused ({e.kind}), {str(e).split(';')[0]}", outcome_category(e.kind)
    except duckdb.Error as e:
        return f"error, {str(e).splitlines()[0]}", "error"
