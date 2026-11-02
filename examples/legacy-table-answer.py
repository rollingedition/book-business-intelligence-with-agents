"""What the legacy mart says about revenue by sales region in 2025, and how often the model chose that mart."""
from lib.golden import golden_result, load_golden
from lib.model import RecordedModel
from lib.prompts import schema_only_messages
from lib.tools import extract_sql
from lib.warehouse import connect, describe_schema

con = connect()
question = next(q for q in load_golden() if q.question_id == "gq-012")
golden = dict(golden_result(con, question))
legacy = dict(con.execute("""SELECT sales_region, sum(revenue) FROM analytics.orders_legacy
                             WHERE year(order_date) = 2025 GROUP BY sales_region""").fetchall())
(test_orders,), = con.execute("""SELECT count(*) FROM analytics.orders_legacy AS l JOIN raw.orders AS o ON o.order_id = l.id
                                 WHERE o.is_test AND year(l.order_date) = 2025""").fetchall()

for region in sorted(golden):
    print(f"{region} golden: {golden[region]:,.2f}")
    print(f"{region} orders_legacy: {legacy[region]:,.2f}")
print(f"legacy total over golden: {sum(legacy.values()) / sum(golden.values()) - 1:+.1%}")
print(f"test orders in the legacy rows: {test_orders}")

# The model's schema-only queries for the first 16 golden questions: did any read the legacy mart?
model, schema = RecordedModel("schema-only-sql"), describe_schema(con)
asked = [q for q in load_golden() if q.question_id <= "gq-016"]
sqls = [extract_sql(model.complete(schema_only_messages(schema, q.question))) for q in asked]
print(f"model queries that read orders_legacy: {sum('orders_legacy' in sql for sql in sqls)} of {len(sqls)}")
print(f"golden questions added in chapter 2, gq-006 to gq-016: {sum('gq-006' <= q.question_id <= 'gq-016' for q in asked)}")
