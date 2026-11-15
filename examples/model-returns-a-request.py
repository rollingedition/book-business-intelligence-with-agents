"""The model returns a metric request, not SQL, and the layer compiles that request. The prose rests on the `matches golden`
line, which the example asserts; the schema-only outcome shows the baseline's failure on the same question."""
from lib.agent import run_agent
from lib.golden import golden_result, load_golden, results_match, schema_only_outcome
from lib.metric_tools import MetricToolbox, catalog
from lib.model import RecordedModel
from lib.prompts import metrics_first_prompt
from lib.semantic import MetricRequest
from lib.warehouse import connect, describe_schema

con = connect()
toolbox = MetricToolbox(con)
system = metrics_first_prompt(catalog(toolbox.layer))
question = next(q for q in load_golden() if q.question_id == "gq-003")
model = RecordedModel("metric-agent-runs")
trace = run_agent(question.question, system, model, toolbox, max_steps=4)     # the chapter's limit of four model calls per run

print(f"question: {question.question}")
print(f"model calls: {sum(step.kind == 'model' for step in trace.steps)}")
print(f"reply: {trace.steps[0].content}")                                   # step 0 is the model's first reply, before any tool runs
print(MetricRequest.from_arguments(trace.steps[0].arguments))               # the reply's arguments, parsed into the typed request
print(trace.answer.provenance.sql)                                          # SQL the layer compiled from the request, not SQL the model wrote
print(trace.answer.show())
matches = results_match(trace.answer.rows, golden_result(con, question))
assert matches, "the layer's answer to gq-003 should match its golden result"   # the request asks gq-003's own question, net revenue by channel for 2025, so its rows are the golden ones
print(f"matches golden: {'yes' if matches else 'no'}")

schema = describe_schema(con)
print(f"schema-only outcome: {schema_only_outcome(con, RecordedModel('schema-only-sql'), schema, question)}")
