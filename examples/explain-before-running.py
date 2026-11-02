"""Bound the rows and the cost: EXPLAIN a join that forgot its keys, keep the agent's LIMIT, and stop a slow query."""
import sqlglot

from lib.golden import load_golden
from lib.sql_guard import GuardError, SqlGuard, check, explain, run_with_timeout
from lib.warehouse import agent_warehouse, connect

guard = SqlGuard(con := agent_warehouse(connect()))   # the agent's database, where the guard runs its checks
NO_KEYS = """SELECT sum(o.net_revenue_eur) AS net_revenue FROM analytics.fct_orders AS o,
analytics.fct_order_lines AS l, analytics.fct_refunds AS r"""
KEYED = """SELECT sum(o.net_revenue_eur) AS net_revenue FROM analytics.fct_orders AS o
JOIN analytics.fct_order_lines AS l USING (order_id)"""
for label, sql in (("no join keys", NO_KEYS), ("joined on order_id", KEYED)):
    cost = explain(con, check(sql, guard.schema).sql)
    print(f"{label}, largest step: {cost.largest_step}\n{label}, estimated rows: {cost.largest_estimate:,}")
try:
    guard.check(NO_KEYS)
except GuardError as e:
    print(f"guard refuses ({e.kind}): {e}")
costs = {q.question_id: explain(con, check(q.golden_sql, guard.schema).sql)
         for q in load_golden() if q.golden_sql and q.question_id not in ("gq-034", "gq-037")}
print("golden queries estimated:", len(costs))
print(f"largest estimate among golden queries: {max(c.largest_estimate for c in costs.values()):,} rows")
print("golden plans with a cross product:", ", ".join(i for i, c in costs.items() if c.cross_products))
print("golden plans with a step that has no estimate:", sum(1 for c in costs.values() if c.unestimated))
print(f"limit on estimated rows: {guard.max_estimated_rows:,}")

TOP_FIVE = """SELECT product_id, sum(net_amount_eur) AS net_revenue FROM analytics.fct_order_lines
GROUP BY product_id ORDER BY net_revenue DESC LIMIT 5"""
print("sqlglot's .limit(1001):", sqlglot.parse_one(TOP_FIVE, read="duckdb").limit(1001).sql("duckdb").split("ORDER BY")[1].strip())
print("guard's limit on the top five:", check(TOP_FIVE, guard.schema).limit)
try:
    guard.run("SELECT order_id, net_revenue_eur FROM analytics.fct_orders")
except GuardError as e:
    print(f"every order ({e.kind}): {e}")

# The join without keys, through the time limit alone, as if the estimate had let it through. It reads its rows in
# batches, and DuckDB looks for the timer's interrupt between them.
try:
    run_with_timeout(con, check(NO_KEYS, guard.schema).sql, seconds=1.0)
except GuardError as e:
    print(f"no join keys, timer alone ({e.kind}): {e}")
print("connection still answers:", con.execute("SELECT count(*) FROM analytics.fct_orders").fetchall()[0][0])

