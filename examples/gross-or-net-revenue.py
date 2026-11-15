"""Replay the model's SQL for total revenue in 2025, then change one choice at a time until it reaches the golden result. The line that matters is `overstated by`, and the step from gross to net, which matches the tax in the gross figure."""
from lib.golden import golden_result, load_golden
from lib.model import RecordedModel
from lib.prompts import schema_only_messages
from lib.tools import extract_sql, run_sql
from lib.warehouse import connect, describe_schema

con = connect()
question = next(q for q in load_golden() if q.question_id == "gq-008")
sql = extract_sql(RecordedModel("schema-only-sql").complete(schema_only_messages(describe_schema(con), question.question)))
print(sql)


def total(measure: str, where: str) -> float:
    return con.execute(f"SELECT sum({measure}) FROM analytics.fct_orders WHERE {where}").fetchall()[0][0]


# The model filters on placed_at, the UTC timestamp, so "2025" here is 2025 by UTC, not by local business day.
utc_2025 = "placed_at >= '2025-01-01' AND placed_at < '2026-01-01'"
model_answer, golden = run_sql(con, sql).rows[0][0], golden_result(con, question)[0][0]
# Each step changes one choice from the step before it, so the values read as a walk to the golden figure.
steps = {
    "model's answer (gross)": model_answer,
    "net instead of gross": total("net_revenue_eur", utc_2025),
    "without cancelled orders": total("net_revenue_eur", f"{utc_2025} AND status <> 'cancelled'"),
    "golden (local business days)": golden,
}
for label, value in steps.items():
    print(f"{label}: {value:,.2f}")
# The tax the gross figure carries, summed over the same rows the model's query reads.
print(f"tax in the gross figure: {total('tax_eur', utc_2025):,.2f}")
print(f"overstated by: {model_answer / golden - 1:.1%}")
