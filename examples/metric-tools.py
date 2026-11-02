"""Give the agent the semantic layer's metrics instead of the warehouse's tables, and compare what each prompt holds."""
from lib.golden import load_golden
from lib.metric_tools import MetricToolbox, catalog
from lib.model import RecordedModel
from lib.prompts import metrics_first_prompt, schema_only_messages
from lib.warehouse import connect, describe_schema

con = connect()
toolbox = MetricToolbox(con)
system = metrics_first_prompt(catalog(toolbox.layer))
print(f"tools: {', '.join(toolbox.tools)}")
print(f"metrics in the prompt: {len(toolbox.layer.metrics)}")
print(f"tables in the prompt: {system.count('CREATE TABLE')}")
print(catalog(toolbox.layer).splitlines()[0])

print(toolbox.call("describe_metric", {"metric": "refund_rate"}).content)

# The first call of the same golden question, gq-002, under each prompt, as the recordings measured it.
question = next(q for q in load_golden() if q.question_id == "gq-002").question
schema_only = schema_only_messages(describe_schema(con), question)
metrics_first = [{"role": "system", "content": system}, {"role": "user", "content": question}]
print(f"schema-only prompt tokens: {RecordedModel('schema-only-sql').call_for(schema_only)['prompt_tokens']}")
print(f"metrics-first prompt tokens: {RecordedModel('metric-agent-runs').call_for(metrics_first)['prompt_tokens']}")
