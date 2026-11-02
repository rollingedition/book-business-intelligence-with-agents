"""Two time traps in the model's SQL: a calendar year where the question meant a fiscal one, and UTC days."""
from lib.golden import golden_result, load_golden
from lib.model import RecordedModel
from lib.prompts import schema_only_messages
from lib.tools import extract_sql, run_sql
from lib.warehouse import connect, describe_schema

con = connect()
schema, model = describe_schema(con), RecordedModel("schema-only-sql")
golden = {q.question_id: q for q in load_golden()}


def model_answer(question_id: str):
    sql = extract_sql(model.complete(schema_only_messages(schema, golden[question_id].question)))
    print(sql)
    return run_sql(con, sql).rows


# gq-004: customers whose first order was in fiscal year 2026, which runs from February 1, 2025 to January 31, 2026.
print(f"gq-004 model: {model_answer('gq-004')[0][0]}")
print(f"gq-004 golden: {golden_result(con, golden['gq-004'])[0][0]}")

# gq-013: orders per region in May 2026. The model filters on placed_at, in UTC; the shop counts local days.
model_rows, golden_rows = dict(model_answer("gq-013")), dict(golden_result(con, golden["gq-013"]))
for region in sorted(golden_rows):
    print(f"gq-013 {region} model: {model_rows[region]}")
    print(f"gq-013 {region} golden: {golden_rows[region]}")
(moved,), = con.execute("""SELECT count(*) FROM analytics.fct_orders
    WHERE (month(placed_at) = 5) <> (month(order_date_local) = 5) AND year(order_date_local) = 2026""").fetchall()
print(f"orders across May's edges: {moved}")

# Which way each of those orders crossed, by region: in May by the model's UTC filter only, or by the local day only.
crossings = con.execute("""SELECT region,
    count(*) FILTER (WHERE in_utc AND NOT in_local), count(*) FILTER (WHERE in_local AND NOT in_utc)
    FROM (SELECT region, placed_at >= '2026-05-01' AND placed_at < '2026-06-01' AS in_utc,
                 order_date_local BETWEEN DATE '2026-05-01' AND DATE '2026-05-31' AS in_local
          FROM analytics.fct_orders) GROUP BY region ORDER BY region""").fetchall()
for region, utc_only, local_only in crossings:
    print(f"gq-013 {region} in May by UTC only: {utc_only}")
    print(f"gq-013 {region} in May by local day only: {local_only}")
print(f"all regions in May by UTC only: {sum(c[1] for c in crossings)}")
print(f"all regions in May by local day only: {sum(c[2] for c in crossings)}")
