"""Replay the model's SQL for net revenue from orders with a tent, then count each order once. Read the `inflated by` line: it is the fan-out, measured with the model's own joins and filters kept as they are."""
from lib.golden import golden_result, load_golden
from lib.model import RecordedModel
from lib.prompts import schema_only_messages
from lib.tools import extract_sql, run_sql
from lib.warehouse import connect, describe_schema

con = connect()
question = next(q for q in load_golden() if q.question_id == "gq-007")
sql = extract_sql(RecordedModel("schema-only-sql").complete(schema_only_messages(describe_schema(con), question.question)))
print(sql)

# The model's own joins and filters, kept as they are, so only the counting changes.
# placed_at is UTC, so EXTRACT gives the year by UTC, as the model wrote it.
matched = """FROM analytics.fct_orders f JOIN analytics.fct_order_lines fl ON f.order_id = fl.order_id
             JOIN analytics.dim_products p ON fl.product_id = p.product_id
             WHERE {product} AND EXTRACT(YEAR FROM f.placed_at) = 2025"""
# The model's name match, which misses shelters, and the whole Tents category, which has them.
by_name, by_category = "p.product_name LIKE '%tent%'", "p.category = 'Tents'"
# One row for each matched line and a count of the distinct orders behind them; the trailing comma unpacks that one row.
(lines, orders), = con.execute(f"SELECT count(*), count(DISTINCT f.order_id) {matched.format(product=by_name)}").fetchall()
# A semi-join: each order's whole net revenue, counted once, however many of its lines match.
once = "SELECT sum(net_revenue_eur) FROM analytics.fct_orders WHERE order_id IN (SELECT f.order_id {matched})"
model_total = run_sql(con, sql).rows[0][0]
counted_once = con.execute(once.format(matched=matched.format(product=by_name))).fetchall()[0][0]
whole_category = con.execute(once.format(matched=matched.format(product=by_category))).fetchall()[0][0]

print(f"rows the join matched: {lines}")
print(f"orders behind them: {orders}")
print(f"model's answer: {model_total:,.2f}")
print(f"each order counted once: {counted_once:,.2f}")
print(f"inflated by: {model_total / counted_once - 1:.1%}")
print(f"tents and shelters, counted once: {whole_category:,.2f}")
print(f"golden: {golden_result(con, question)[0][0]:,.2f}")

# The same query shape with no product filter: every 2025 order joined to all of its lines.
# `/` is decimal division in DuckDB, so the average keeps its fraction.
(per_order,), = con.execute("SELECT count(*) / count(DISTINCT order_id) FROM analytics.fct_order_lines").fetchall()
# The second subquery is the true sum: each 2025 order counted once, from the orders table alone.
(all_joined, all_once), = con.execute("""SELECT
    (SELECT sum(f.net_revenue_eur) FROM analytics.fct_orders f JOIN analytics.fct_order_lines fl ON f.order_id = fl.order_id
     WHERE EXTRACT(YEAR FROM f.placed_at) = 2025),
    (SELECT sum(net_revenue_eur) FROM analytics.fct_orders WHERE EXTRACT(YEAR FROM placed_at) = 2025)""").fetchall()
print(f"lines per order: {per_order:.2f}")
print(f"all 2025 orders joined to their lines, sum over true sum: {all_joined / all_once:.2f}")
