"""Ask back when a question could mean several metrics: the layer supplies each option's definition to the person."""
from lib.agent import run_agent
from lib.golden import load_golden
from lib.metric_tools import MetricToolbox, catalog, unbounded_ranking
from lib.model import RecordedModel
from lib.prompts import metrics_first_prompt
from lib.semantic import MetricRequest
from lib.warehouse import connect

con = connect()
toolbox = MetricToolbox(con)
system = metrics_first_prompt(catalog(toolbox.layer))
model = RecordedModel("metric-agent-runs")
traces = {q.question_id: run_agent(q.question, system, model, MetricToolbox(con, toolbox.layer, role=q.role),
                                   max_steps=4) for q in load_golden()}
for q in load_golden():
    if q.split == "dev" and q.kind == "decline":
        last = next(s for s in reversed(traces[q.question_id].steps) if s.kind == "model")
        print(f"{q.question_id} ({q.decline_type}): {last.tool}")
        print(f"  {q.question}")

print("gq-019 asks back:")
print(traces["gq-019"].answer.reason)
print("gq-005 asks back:")
print(traces["gq-005"].answer.reason)
answered = next(s for s in reversed(traces["gq-020"].steps) if s.tool == "query_metric")
print(f"gq-020 request: {answered.arguments}")
print(traces["gq-020"].answer.show())

# A check the recorded runs didn't have: refuse a request that ranks its result over no period.
# Applied here to the last request of every run, dev and test, that returned a result.
final = {question_id: MetricRequest.from_arguments(next(s for s in reversed(t.steps) if s.tool == "query_metric")
                                                   .arguments)
         for question_id, t in traces.items() if t.answer.answered}
flagged = [question_id for question_id, request in final.items() if unbounded_ranking(request)]
print(f"runs with a result: {len(final)}")
print(f"requests that order their result: {sum(bool(r.order_by) for r in final.values())}")
print(f"ranking check flags: {', '.join(flagged) or 'none'}")
print(f"ranking check on gq-020: {unbounded_ranking(final['gq-020'])}")
