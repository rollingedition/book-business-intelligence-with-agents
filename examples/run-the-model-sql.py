"""Run the SQL the model wrote for net revenue by region in March 2026, and check it against the golden result. The prose reads each region's model, golden and cancelled-orders lines, and the final match line."""
from lib.golden import golden_result, load_golden, results_match
from lib.model import RecordedModel
from lib.prompts import schema_only_messages
from lib.tools import extract_sql, run_sql
from lib.warehouse import connect, describe_schema

con = connect()
question = next(q for q in load_golden() if q.question_id == "gq-002")   # gq-002: net revenue in each region in March 2026
reply = RecordedModel("schema-only-sql").complete(schema_only_messages(describe_schema(con), question.question))

model_answer = dict(run_sql(con, extract_sql(reply)).rows)   # the query returns (region, net revenue) rows, keyed here by region
golden = dict(golden_result(con, question))
# order_date_local is a date, so BETWEEN with March 31 includes all of March.
cancelled = dict(con.execute("""
    SELECT region, sum(net_revenue_eur) FROM analytics.fct_orders
    WHERE status = 'cancelled' AND order_date_local BETWEEN DATE '2026-03-01' AND DATE '2026-03-31'
    GROUP BY region""").fetchall())

for region in sorted(golden):
    print(f"{region} model: {model_answer[region]:,.2f}")
    print(f"{region} golden: {golden[region]:,.2f}")
    print(f"{region} cancelled orders: {cancelled[region]:,.2f}")
print(f"model total: {sum(model_answer.values()):,.2f}")
print(f"golden total: {sum(golden.values()):,.2f}")
# as a share of the golden total
print(f"overstated by: {sum(model_answer.values()) / sum(golden.values()) - 1:.1%}")
matches = results_match(model_answer.items(), golden.items())
assert not matches           # the model's SQL keeps cancelled orders, so its rows can't equal the golden rows
print(f"matches golden: {'yes' if matches else 'no'}")
