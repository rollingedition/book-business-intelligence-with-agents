"""Draw each golden query's largest estimated step, and the keyless join's cross product, against the guard's limit on
estimated rows. The printed lines are the values the prose quotes: how many golden estimates are small, the largest golden
estimate, the cross product's estimate, and how many times the limit sits over the largest golden estimate and the cross
product over the limit."""
import lib  # noqa: F401  (first, so threads and seeds are fixed before any numerical library loads)
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
# DuckDB's estimates for tiny plans change from one run to the next, so each under 1,000 rows is drawn at 1,000. The
# largest estimates are the same on every run, and they are what the figure is for.
drawn = [max(estimate, 1_000) for estimate in golden.values()]

fig, ax = new_figure(height=2.6)
offsets = [i % 5 * 0.06 for i in range(len(golden))]   # a fixed height per dot, so dots with close estimates don't overlap
ax.scatter(drawn, offsets, color=MUTED, s=18, label="golden queries, one dot each (under 1,000 drawn at 1,000)")
ax.scatter([no_keys], [0.5], color=ACCENT, s=40, label=f"join with no keys, a cross product, {no_keys:,} rows")
ax.axvline(limit, color=INK, linestyle="--", linewidth=1.2, label=f"limit on estimated rows, {limit:,}")
ax.set_xscale("log")
ax.set_xlim(1, 10 ** 12)                               # fixed, so the layout doesn't depend on the data's span
ax.set_yticks([])
ax.set_xlabel("rows estimated for the largest step, log scale")
ax.set_ylim(-0.2, 0.8)
ax.legend(frameon=False, loc="upper left")
save(fig, "plan-row-estimates")

print(f"golden queries estimated: {len(golden)}")
print(f"golden queries under 1,000 rows: {sum(e < 1_000 for e in golden.values())}")
print(f"largest golden estimate: {largest:,} rows")
print(f"join with no keys, cross product estimate: {no_keys:,} rows")
print(f"limit on estimated rows: {limit:,}")
print(f"limit over the largest golden estimate: {round(limit / largest)} times")
print(f"cross product over the limit: {round(no_keys / limit):,} times")
