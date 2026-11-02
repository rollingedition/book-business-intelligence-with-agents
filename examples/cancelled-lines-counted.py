"""Replay the model's SQL for units sold by category in 2025, and find the filters it left out."""
from lib.golden import golden_result, load_golden
from lib.model import RecordedModel
from lib.prompts import schema_only_messages
from lib.tools import extract_sql, run_sql
from lib.warehouse import connect, describe_schema

con = connect()
question = next(q for q in load_golden() if q.question_id == "gq-015")
sql = extract_sql(RecordedModel("schema-only-sql").complete(schema_only_messages(describe_schema(con), question.question)))
print(sql)
model_units = dict(run_sql(con, sql).rows)
golden_units = dict(golden_result(con, question))
(cancelled,), = con.execute("""SELECT sum(l.quantity) FROM analytics.fct_order_lines AS l
    JOIN analytics.fct_orders AS o USING (order_id)
    WHERE o.status = 'cancelled' AND o.placed_at >= '2025-01-01' AND o.placed_at < '2026-01-01'""").fetchall()
(test_units,), = con.execute("""SELECT sum(l.quantity) FROM raw.order_lines AS l JOIN raw.orders AS o USING (order_id)
    WHERE o.is_test AND year(o.placed_at) = 2025""").fetchall()

print(f"Cooking model: {model_units['Cooking']}")
print(f"Cooking golden: {golden_units['Cooking']}")
print(f"all categories model: {sum(model_units.values())}")
print(f"all categories golden: {sum(golden_units.values())}")
print(f"units on cancelled orders, in the model's dates: {cancelled}")
print(f"overstated by: {sum(model_units.values()) / sum(golden_units.values()) - 1:.1%}")
print(f"units on test orders, which the marts already leave out: {test_units}")

# Orders that weren't cancelled but fall in 2025 by one clock and not the other: in by UTC only, minus in by local day only.
(edge_net,), = con.execute("""SELECT sum(l.quantity) FILTER (WHERE year(o.placed_at) = 2025 AND year(o.order_date_local) <> 2025)
                                   - sum(l.quantity) FILTER (WHERE year(o.placed_at) <> 2025 AND year(o.order_date_local) = 2025)
    FROM analytics.fct_order_lines AS l JOIN analytics.fct_orders AS o USING (order_id)
    WHERE o.status <> 'cancelled'""").fetchall()
print(f"net units on orders across the year's edges: {edge_net}")
