"""The critics' attempts to get past the guard (lib/guard_attacks.py), replayed on the agent's database, a temporary
copy of the marts: what the database alone allows, and what the guard does."""
import duckdb

from lib.guard_attacks import ALONE, ATTEMPTS, alone, attempt, macro_then_sum
from lib.sql_guard import SqlGuard, explain
from lib.warehouse import agent_warehouse, connect

agent = agent_warehouse(connect())
guard = SqlGuard(agent)                       # the 5-second limit: the queries that run here finish far inside it
for label, sql in ATTEMPTS.items():
    if label in ALONE:                        # straight to the agent's database, with no guard in front
        print(f"{label}, database alone: {alone(agent, label)}")
    print(f"{label}, guard: {attempt(guard.run, sql)[0]}")
print("upper-case names, guard:", attempt(guard.run, "SELECT count(*) AS n FROM ANALYTICS.FCT_ORDERS")[0])

# A temporary macro named sum, on a cursor of the database alone, then sent straight to the guard's worker.
alone_sum, real = macro_then_sum(agent, guard.worker)
print("temp macro named sum, database alone, the next sum:", alone_sum)
print("temp macro named sum, guard's worker, the next sum is the real one:", real)

# The regex attempt. In-process, a timer's interrupt waits for the end of a batch of rows, and one batch is this much
# text. With repeat() and regexp_matches() (sqlglot's REGEXP_LIKE) allowed, the guard's worker runs it under the
# review's 2-second limit, and stops it by the deadline or the memory cap, whichever the machine reaches first.
REGEX, BATCH = ATTEMPTS["regex on a repeated email"], duckdb.__standard_vector_size__
(text,), = agent.execute(f"SELECT sum(length(email)) * 200000 FROM (SELECT email FROM analytics.dim_customers "
                         f"ORDER BY customer_id LIMIT {BATCH})").fetchall()
print(f"regex, characters to match in one batch of {BATCH:,} rows: {text:,}")
wider = SqlGuard(agent, timeout=2.0, functions=guard.functions | {"repeat", "regexp_like"})
print("regex, guard without the function list:", attempt(wider.run, REGEX)[1])
print("regex, worker still running afterwards:", wider.worker_running)
print("regex, the guard's next query:", attempt(wider.run, "SELECT count(*) AS n FROM analytics.fct_orders")[0])

# The inequality join ran. Its estimate varies a little between runs, so only its size is printed.
JOIN = ATTEMPTS["join on inequality"]
estimate, joined = explain(agent, JOIN).largest_estimate, guard.run(JOIN).rows[0][0]
print("join on inequality, estimate under the limit:", estimate < guard.max_estimated_rows)
print(f"join on inequality, rows it joined: {joined:,}")
print("join on inequality, rows joined more than 100 times the estimate:", joined > 100 * estimate)
