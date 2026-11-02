"""The table allowlist: the marts the agent may read, the ways around it the guard refuses, and what it costs."""
from lib.golden import load_golden
from lib.sql_guard import GuardError, SqlGuard
from lib.warehouse import agent_warehouse, connect

con = agent_warehouse(connect())          # the agent's database: copies of the allowed marts, nothing else
guard = SqlGuard(con)                     # allowlist: the tables in it, read with their columns
print("allowed tables:", ", ".join(f"{db}.{t}" for db, tables in guard.schema.items() for t in tables))

ATTEMPTS = {
    "raw table": "SELECT count(*) AS customers FROM raw.customers",
    "legacy mart": "SELECT sum(revenue) AS revenue FROM analytics.orders_legacy",
    "no schema": "SELECT count(*) AS orders FROM fct_orders",
    "file as a table": "SELECT * FROM 'data/golden/questions.toml'",
    "table function": "SELECT * FROM read_csv('data/golden/questions.toml')",
    "CTE named like the catalog": """SELECT * FROM (WITH duckdb_tables AS (SELECT 1 AS x) SELECT x FROM duckdb_tables) AS a,
duckdb_tables""",
}
for label, sql in ATTEMPTS.items():
    try:
        guard.check(sql)
        print(f"{label}: allowed")
    except GuardError as e:
        print(f"{label}: refused ({e.kind}), {str(e).split(';')[0]}")

golden = [q for q in load_golden() if q.golden_sql]
outside = []
for q in golden:
    try:
        guard.check(q.golden_sql)
    except GuardError as e:
        outside.append(f"{q.question_id} ({str(e).split(' ')[0]})")
print(f"golden queries the allowlist refuses: {len(outside)} of {len(golden)}")
print("refused golden queries:", ", ".join(outside))
