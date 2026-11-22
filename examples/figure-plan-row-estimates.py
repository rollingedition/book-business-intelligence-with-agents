"""Draw each golden query's largest estimated step, and the keyless join's, against the guard's limit on estimated rows.
Estimates under 1,000 rows are drawn at 1,000, because DuckDB's estimates for tiny plans change from run to run. The
printed lines are the values the prose and narration quote: the golden count, the largest golden estimate, and how many
times the keyless join's estimate is over the limit."""
import lib  # noqa: F401  (first, so threads and seeds are fixed before any numerical library loads)
from collections import Counter

from lib.figures import ACCENT, INK, MUTED, new_figure, save
from lib.golden import load_golden
from lib.sql_guard import SqlGuard, check, explain
from lib.warehouse import agent_warehouse, connect

guard = SqlGuard(con := agent_warehouse(connect()))   # the agent's database, where the guard plans each query
NO_KEYS = """SELECT sum(o.net_revenue_eur) AS net_revenue FROM analytics.fct_orders AS o,
analytics.fct_order_lines AS l, analytics.fct_refunds AS r"""
no_keys = explain(con, check(NO_KEYS, guard.schema).sql).largest_estimate
# The same golden queries as the explain example: gq-034 and gq-037 need tables off the list, so they are left out.
golden = {q.question_id: explain(con, check(q.golden_sql, guard.schema).sql).largest_estimate
          for q in load_golden() if q.golden_sql and q.question_id not in ("gq-034", "gq-037")}
limit = guard.max_estimated_rows
largest = max(golden.values())
drawn = [max(estimate, 1_000) for estimate in golden.values()]   # each under 1,000 rows is drawn at 1,000

fig, ax = new_figure(height=2.6)
seen = Counter()
offsets = []                                           # each dot with the same drawn value gets its own height
for value in drawn:
    offsets.append(seen[value] * 0.05)
    seen[value] += 1
ax.scatter(drawn, offsets, color=MUTED, s=18, label="golden queries (under 1,000 at 1,000)")
ax.scatter([no_keys], [0.6], color=ACCENT, s=40, label="join with no keys")
ax.axvline(limit, color=INK, linestyle="--", linewidth=1.2, label=f"limit, {limit:,} rows")
ax.set_xscale("log")
ax.set_xlim(500, 10 ** 12)                             # starts below the floor, so nothing is drawn under it
ax.set_yticks([])
ax.set_xlabel("rows estimated for the largest step, log scale")
ax.set_ylim(-0.1, 1.2)
ax.legend(frameon=False, loc="lower right")
save(fig, "plan-row-estimates")

print(f"golden queries estimated: {len(golden)}")
print(f"largest golden estimate: {largest:,} rows")
print(f"join with no keys over the limit: {round(no_keys / limit):,} times")
