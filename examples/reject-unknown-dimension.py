"""Validate a metric request against the layer and the warehouse before it runs, and show what would run without it."""
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
print(f"unchecked, region Europe: {layer.query(con, request).rows}")

# The model's own requests for gq-002, net revenue in each region in March 2026, replayed from the recording.
question = next(q for q in load_golden() if q.question_id == "gq-002")
system = metrics_first_prompt(catalog(layer))
trace = run_agent(question.question, system, RecordedModel("metric-agent-runs"), toolbox, max_steps=4)
first, second = (MetricRequest.from_arguments(s.arguments) for s in trace.steps if s.tool == "query_metric")
golden = golden_result(con, question)
unchecked = layer.query(con, first)                # what would have run without validation
print(f"first request filters: {first.filters}")
print(f"unchecked total: {sum(row[1] for row in unchecked.rows):,.2f}")
print(f"golden total: {sum(row[1] for row in golden):,.2f}")
print(f"unchecked matches golden: {results_match(unchecked.rows, golden)}")
print(f"validation said: {trace.steps[1].content}")
print(f"second request filters: {second.filters}")
print(f"matches golden: {results_match(trace.answer.rows, golden)}")
