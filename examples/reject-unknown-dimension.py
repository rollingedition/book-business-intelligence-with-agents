"""Validate a metric request against the layer and the warehouse before it runs, and show what would run without it.
The prose rests on the unchecked total and the two `matches golden` lines; the example asserts the two matches."""
from lib.agent import run_agent
from lib.golden import golden_result, load_golden, results_match
from lib.metric_tools import MetricToolbox, catalog, validate_request
from lib.model import RecordedModel
from lib.prompts import metrics_first_prompt
from lib.semantic import MetricRequest
from lib.warehouse import connect

con = connect()
toolbox = MetricToolbox(con)
layer = toolbox.layer
for label, request in [("no such dimension", MetricRequest(("orders",), group_by=("customer__email",))),
                       ("fan-out", MetricRequest(("net_revenue",), group_by=("product__category",))),
                       ("no such value", MetricRequest(("net_revenue",), filters={"order__region": "Europe"}))]:
    print(f"{label}: {validate_request(layer, con, request)[0]}")
print(f"unchecked, region Europe: {layer.query(con, request).rows}")           # `request` is still the Europe filter from the loop

# The model's own requests for gq-002, net revenue in each region in March 2026, replayed from the recording.
question = next(q for q in load_golden() if q.question_id == "gq-002")
system = metrics_first_prompt(catalog(layer))
trace = run_agent(question.question, system, RecordedModel("metric-agent-runs"), toolbox, max_steps=4)
first, second = (MetricRequest.from_arguments(s.arguments) for s in trace.steps if s.tool == "query_metric")   # its two query calls
golden = golden_result(con, question)
unchecked = layer.query(con, first)                # what would have run without validation
print(f"first request filters: {first.filters}")
print(f"unchecked total: {sum(row[1] for row in unchecked.rows):,.2f}")           # row[1] is the net revenue column
print(f"golden total: {sum(row[1] for row in golden):,.2f}")
unchecked_matches = results_match(unchecked.rows, golden)
assert not unchecked_matches, "the unchecked request should miss the golden result"   # a month written against a daily date dimension matches only its first day, so this total can't cover the month
print(f"unchecked matches golden: {'yes' if unchecked_matches else 'no'}")
print(f"validation said: {trace.steps[1].content}")                               # step 1 is the refusal the layer returned
print(f"second request filters: {second.filters}")
matches = results_match(trace.answer.rows, golden)
assert matches, "the second request should match the golden result"              # filtering metric_time at the month's grain covers every day in March, the golden question's period
print(f"matches golden: {'yes' if matches else 'no'}")
