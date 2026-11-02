"""Stop a slow plan: DuckDB computes a constant while it plans, before any row is read, so a timer's interrupt has
nothing to stop it at; a killed worker stops wherever it is."""
import json

from lib.sql_guard import GuardError, SqlGuard, Worker, check
from lib.warehouse import agent_warehouse, connect

shop = connect()                                      # chapter 1's connection: constant folding on
agent = agent_warehouse(shop)                         # the agent's database: constant folding off
guard = SqlGuard(agent, timeout=0.5)
SLOW_PLAN = """SELECT count(*) AS n FROM analytics.fct_orders
WHERE order_id < list_sum(list_transform(range(30000000), x -> list_sum(range(40))))"""
# Checked as if the function list allowed the list functions, as sqlglot names them (range() is GENERATE_SERIES and
# list_transform() is TRANSFORM), so the plan reaches DuckDB.
LIST_FUNCTIONS = {"list_sum", "transform", "generate_series"}
planned = check(SLOW_PLAN, guard.schema, functions=guard.functions | LIST_FUNCTIONS).sql
# The same query with a small constant, 3 lists summing to 6 each: 18, under every order ID. A plan with no rows to
# read means DuckDB computed the constant while planning.
small = planned.replace("30000000", "3").replace("RANGE(0, 40)", "RANGE(0, 4)")
for label, connection in (("shop's connection, folding on", shop), ("agent's database, folding off", agent)):
    (_, plan), = connection.execute(f"EXPLAIN (FORMAT json) {small}").fetchall()
    steps, nodes = [], json.loads(plan)
    while nodes:
        steps.append(nodes[0]["name"])
        nodes = nodes[0]["children"]
    print(f"EXPLAIN with a small constant, {label}: {' > '.join(steps)}")
worker = Worker(shop)                                 # a process with its own connection to the shop's file
try:
    worker.explain(planned, 0.5)
    outcome = "planned"
except GuardError as e:
    outcome = e.kind                                  # timeout, memory or worker_failed: the machine decides which
print("EXPLAIN in a worker with a half-second deadline, shop's connection, plan returned:", outcome == "planned")
print("EXPLAIN in a worker, still running afterwards:", worker.running)
try:
    guard.run(SLOW_PLAN)
except GuardError as e:
    print(f"slow plan through the guard ({e.kind}): {e}")
