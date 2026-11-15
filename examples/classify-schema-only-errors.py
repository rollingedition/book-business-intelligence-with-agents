"""Run the model's schema-only SQL on each golden question that has an answer, grade each result, and label the failure kinds of each query. The counts of correct, wrong and error answers, and the kinds the wrong ones carry, are what the prose quotes."""
from collections import Counter

import duckdb
from lib.failure_kinds import KINDS, failure_kinds
from lib.golden import golden_result, grade, load_golden
from lib.model import RecordedModel
from lib.prompts import schema_only_messages
from lib.tools import extract_sql, run_sql
from lib.warehouse import connect, describe_schema

con = connect()
schema, model = describe_schema(con), RecordedModel("schema-only-sql")
# Kind "answer" leaves out gq-005, the forecast to decline; IDs are zero-padded, so gq-001 to gq-016 is a text range.
questions = [q for q in load_golden() if q.kind == "answer" and q.question_id <= "gq-016"]
outcomes, kinds_in_wrong, errors = Counter(), Counter(), {}

print("question  outcome  kinds")
for q in questions:
    sql = extract_sql(model.complete(schema_only_messages(schema, q.question)))
    try:
        outcome = grade(q, run_sql(con, sql), golden_result(con, q))
    except duckdb.Error as e:
        # A query the database refuses to run is an error, not a wrong number.
        outcome, errors[q.question_id] = "error", str(e).splitlines()[0]
    # Each kind is a rule in lib/failure_kinds.py that compares the query with the golden SQL; a query can carry none or several.
    kinds = failure_kinds(sql, q.golden_sql)
    outcomes[outcome] += 1
    if outcome == "wrong":
        kinds_in_wrong.update(kinds)
    print(f"{q.question_id}    {outcome:<7}  {', '.join(kinds) or '-'}")

for question_id, message in errors.items():
    print(f"{question_id} error: {message}")
print(f"questions graded: {len(questions)}")
for outcome in ("correct", "wrong", "error"):
    print(f"{outcome}: {outcomes[outcome]} of {len(questions)}")
# DuckDB's messages: one for a column the table read does not have, one for a type mismatch such as LIKE on a timestamp.
print(f"errors with a missing column: {sum('Referenced column' in m for m in errors.values())}")
print(f"errors with a type mismatch: {sum('No function matches' in m for m in errors.values())}")
for kind in KINDS:
    print(f"wrong answers with {kind}: {kinds_in_wrong[kind]}")

# gq-016 counts distinct customers: do those with an order across 2025's edges have other 2025 orders by both clocks?
(edge_customers, covered), = con.execute("""SELECT count(DISTINCT customer_id), count(DISTINCT customer_id) FILTER (WHERE customer_id IN
    (SELECT customer_id FROM analytics.fct_orders WHERE year(placed_at) = 2025 AND year(order_date_local) = 2025))
    FROM analytics.fct_orders WHERE (year(placed_at) = 2025) <> (year(order_date_local) = 2025)""").fetchall()
print(f"gq-016 customers with an order across 2025's edges: {edge_customers}")
print(f"gq-016 of them, with other 2025 orders by both clocks: {covered}")
