"""Load the shop's 48 golden questions, show what one holds and how the set divides, and compute one gold's other reading."""
from collections import Counter

from lib.golden import golden_result, load_golden
from lib.warehouse import connect

con = connect()
questions = load_golden()
print(f"golden questions: {len(questions)}")
for kind, count in sorted(Counter(q.kind for q in questions).items()):
    print(f"{kind}: {count}")
for decline_type, count in sorted(Counter(q.decline_type for q in questions if q.kind == "decline").items()):
    print(f"decline, {decline_type}: {count}")
print(f"roles: {', '.join(sorted({q.role for q in questions}))}")

q = next(q for q in questions if q.question_id == "gq-018")
print()
print(f"{q.question_id} ({q.split}, {q.kind}, asked by {q.role})")
print(f"question: {q.question}")
print(f"golden SQL: {' '.join(q.golden_sql.split())}")
print(f"traps: {', '.join(q.traps)}")
print(f"note: {q.note}")

# The other reading: refunds grouped by the month they were made, not the month the order was placed.
by_refund_month = con.execute(
    "SELECT round(sum(amount_eur), 2) FROM analytics.fct_refunds WHERE refund_month = DATE '2026-03-01'").fetchall()
print(f"refunded on orders placed in March 2026: {golden_result(con, q)[0][0]:,.2f}")
print(f"refunded in March 2026, by refund month: {by_refund_month[0][0]:,.2f}")
