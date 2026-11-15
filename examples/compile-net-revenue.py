"""Compile one metric request to SQL with the book's semantic layer, run it, and check it against the golden answer. The printed `matches golden: yes` line is the fact the prose states."""
from lib.golden import golden_result, load_golden, results_match
from lib.semantic import MetricRequest, SemanticError, load
from lib.warehouse import connect

layer, con = load(), connect()
question = next(q for q in load_golden() if q.question_id == "gq-002")
print(f"question: {question.question}")

request = MetricRequest(metrics=("net_revenue",), group_by=("order__region",),
                        filters={"metric_time__month": "2026-03"})  # the compiler turns this text month into a date literal, compared with a date cast
print(f"request: {request}")
print(layer.sql(request))

answer = layer.query(con, request)
print(answer.show())
matches = results_match(answer.rows, golden_result(con, question))
assert matches, "gq-002 must match its golden result"
print(f"matches golden: {'yes' if matches else 'no'}")

# A filter value becomes a literal in the expression tree, so text in it can't change the query.
hostile = MetricRequest(("net_revenue",), filters={"order__region": "EMEA' OR '1'='1"})
condition = layer.compile(hostile).args["where"].sql(dialect="duckdb")
print(f"hostile filter compiles to: {condition}")
print(f"rows for the hostile value: {layer.query(con, hostile).rows}")

# A name the layer doesn't define is refused before any SQL exists, with what the metric can use.
try:
    layer.compile(MetricRequest(("net_revenue",), ("order__colour",)))
except SemanticError as e:
    print(f"refused: {e}")
