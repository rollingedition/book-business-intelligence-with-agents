"""The model returns a metric request, not SQL: the layer compiles the request, and the answer is checked against gold."""
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
trace = run_agent(question.question, system, model, toolbox, max_steps=4)

print(f"question: {question.question}")
print(f"model calls: {sum(step.kind == 'model' for step in trace.steps)}")
print(f"reply: {trace.steps[0].content}")
print(MetricRequest.from_arguments(trace.steps[0].arguments))
print(trace.answer.provenance.sql)
print(trace.answer.show())
print(f"matches golden: {results_match(trace.answer.rows, golden_result(con, question))}")

schema = describe_schema(con)
print(f"schema-only outcome: {schema_only_outcome(con, RecordedModel('schema-only-sql'), schema, question)}")
