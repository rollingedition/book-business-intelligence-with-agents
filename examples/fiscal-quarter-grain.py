"""Group net revenue by fiscal quarter, a custom grain from the time spine, and by calendar quarter, a standard one."""
from datetime import date

from lib.golden import golden_result, load_golden, results_match
from lib.semantic import MetricRequest, load
from lib.warehouse import connect

layer, con = load(), connect()

fiscal = MetricRequest(("net_revenue",), ("metric_time__fiscal_quarter",), {"metric_time__fiscal_year": 2026})
print(layer.sql(fiscal))
fiscal_answer = layer.query(con, fiscal)
print(fiscal_answer.show())

calendar = MetricRequest(("net_revenue",), ("metric_time__quarter",), {"metric_time__year": 2025})
calendar_answer = layer.query(con, calendar)
print(calendar_answer.show())
print(f"fiscal 2026-Q1, February to April 2025: {dict(fiscal_answer.rows)["2026-Q1"]:,.2f}")
print(f"calendar 2025 Q1, January to March 2025: {dict(calendar_answer.rows)[date(2025, 1, 1)]:,.2f}")

golden = {q.question: q for q in load_golden()}
for text, request in [
    ("What was net revenue in the first quarter of fiscal year 2026?",
     MetricRequest(("net_revenue",), filters={"metric_time__fiscal_quarter": "2026-Q1"})),
    ("What was net revenue in each region in the first quarter of fiscal year 2027?",
     MetricRequest(("net_revenue",), ("order__region",), {"metric_time__fiscal_quarter": "2027-Q1"})),
]:
    question = golden[text]
    answer = layer.query(con, request)
    print(f"{question.question_id} matches golden: {results_match(answer.rows, golden_result(con, question))}")
