"""A DELETE hidden in a CTE: the root says SELECT, the tree walk finds the DELETE, and the read-only warehouse refuses it.

The attack runs for real only on a throwaway copy of the shop, built from the same seed in a temporary folder.
"""
import tempfile
from pathlib import Path

import duckdb
import sqlglot
from sqlglot import exp

from lib.sql_guard import GuardError, SqlGuard
from lib.warehouse import agent_warehouse, build, connect

ATTACK = """WITH gone AS (DELETE FROM analytics.fct_refunds WHERE amount_eur > 50 RETURNING refund_id)
SELECT count(*) AS refunds_over_50 FROM gone"""

tree = sqlglot.parse_one(ATTACK, read="duckdb")
print("root:", type(tree).__name__)
print("statements in the tree:", ", ".join(type(n).__name__ for n in tree.walk() if isinstance(n, (exp.Query, exp.DML))))

agent = agent_warehouse(connect())                      # the agent's read-only database
try:
    SqlGuard(agent).run(ATTACK)
except GuardError as e:
    print(f"guard refuses ({e.kind}): {e}")
try:
    agent.execute(ATTACK)                                 # past the guard, straight to the read-only database
except duckdb.Error as e:
    print("read-only database:", str(e).splitlines()[0])

with tempfile.TemporaryDirectory() as folder:             # a writable copy, deleted when the block ends
    path = Path(folder) / "shop.duckdb"
    build(path)
    with duckdb.connect(str(path)) as writable:
        (before,), = writable.execute("SELECT count(*) FROM analytics.fct_refunds").fetchall()
        (answer,), = writable.execute(ATTACK).fetchall()
        (after,), = writable.execute("SELECT count(*) FROM analytics.fct_refunds").fetchall()
print("writable copy, refunds before:", before)
print("writable copy, the query's answer:", answer)
print("writable copy, refunds after:", after)
