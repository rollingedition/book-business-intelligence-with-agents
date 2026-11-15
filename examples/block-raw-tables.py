"""The table allowlist: the marts the agent may read, six ways around it that the guard refuses, and the two golden
queries it can't answer. The last two lines are the cost the prose describes."""
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
        print(f"{label}: refused ({e.kind}), {str(e).split(';')[0]}")   # the message's first clause

golden = [q for q in load_golden() if q.golden_sql]
outside = []
for q in golden:
    try:
        guard.check(q.golden_sql)
    except GuardError as e:
        outside.append(f"{q.question_id} ({str(e).split(' ')[0]})")   # the message starts with the table it refused
print(f"golden queries the allowlist refuses: {len(outside)} of {len(golden)}")
print("refused golden queries:", ", ".join(outside))
