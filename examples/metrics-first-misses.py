"""Read every metrics-first run that wasn't correct, call by call, and ask the layer what gq-039's run was reaching for.
The prose rests on the gq-039 line: the layer's own request for it matches the golden result, and the run never found it."""
import json

from lib.agent import run_agent
from lib.golden import golden_result, grade, load_golden, results_match
from lib.metric_tools import MetricToolbox, catalog
from lib.model import RecordedModel
from lib.prompts import metrics_first_prompt
from lib.semantic import MetricRequest, load
from lib.warehouse import connect

con, layer = connect(), load()
system, model, golden = metrics_first_prompt(catalog(layer)), RecordedModel("metric-agent-runs"), load_golden()
for q in golden:
    trace = run_agent(q.question, system, model, MetricToolbox(con, layer, role=q.role), max_steps=4)
    outcome, answer = grade(q, trace.answer, golden_result(con, q)), trace.answer
    calls = list(zip(trace.steps[::2], trace.steps[1::2]))      # each model reply, then what its tool returned
    if q.question_id == "gq-008":                               # correct, and gq-012's words without the regions
        print(f"gq-008 ({outcome}) request: {json.dumps(calls[-1][0].arguments)}")
    if outcome == "correct":
        continue
    print(f"{q.question_id} ({q.split}, {q.kind}, {outcome}): {q.question}")
    print(f"{q.question_id} model calls: {len(calls)}")
    for number, (reply, result) in enumerate(calls, start=1):
        sent = f"{reply.tool} {json.dumps(reply.arguments)}" if reply.tool else reply.content
        got = result.content.splitlines()[0][:150]                              # the result's first line, cut to 150 characters
        ended = {"metric": f"{len(answer.rows)} row" + "s" * (len(answer.rows) != 1), "none": "declined",
                 "ask_back": "asked back"}
        if number == len(calls) and answer.provenance.source in ended:
            got = ended[answer.provenance.source]
        print(f"  {number}. {sent} -> {got}")
    if answer.answered:
        print(f"{q.question_id} rows: {len(answer.rows)}")

# gq-039 is answerable from the layer: the request its run was reaching for, with the order written as "-name".
gq039 = next(q for q in golden if q.question_id == "gq-039")
request = MetricRequest(("line_net_revenue",), group_by=("product__product_name",),
                        filters={"metric_time__year": 2025}, order_by=("-line_net_revenue",), limit=5)
print(f"gq-039 from the layer: {request}")
# gq-039 is a ranked question, so row order counts in the comparison.
matched = results_match(layer.query(con, request).rows, golden_result(con, gq039), gq039.order_matters)
assert matched, "the layer's request for gq-039 should match its golden result"   # the request asks gq-039's question, the five products with the most net revenue in 2025, highest first
print(f"gq-039 from the layer, matches golden: {'yes' if matched else 'no'}")
