"""Score both approaches on five golden questions: schema-only SQL, and the agent with one defined metric."""
from collections import Counter

import duckdb
from lib.agent import run_agent
from lib.golden import golden_result, grade, load_golden
from lib.metrics import METRICS
from lib.model import RecordedModel
from lib.prompts import metric_tools_prompt, schema_only_messages
from lib.tools import Toolbox, extract_sql, run_sql
from lib.warehouse import connect, describe_schema

con = connect()
schema, system = describe_schema(con), metric_tools_prompt(METRICS.values())
sql_model, metric_model = RecordedModel("schema-only-sql"), RecordedModel("metric-tool-runs")
totals = {"schema-only": Counter(), "metric": Counter()}

print("question  kind     schema-only  metric")
for q in load_golden()[:5]:      # the first five; chapter 3 builds the full set
    golden = golden_result(con, q)
    try:
        sql = extract_sql(sql_model.complete(schema_only_messages(schema, q.question)))
        sql_outcome = grade(q, run_sql(con, sql), golden)
    except duckdb.Error:
        sql_outcome = "error"
    metric_outcome = grade(q, run_agent(q.question, system, metric_model, Toolbox(con)).answer, golden)
    totals["schema-only"][sql_outcome] += 1
    totals["metric"][metric_outcome] += 1
    print(f"{q.question_id}    {q.kind:<7}  {sql_outcome:<11}  {metric_outcome}")

for name, counts in totals.items():
    for outcome in ("correct", "wrong", "error", "declined"):
        print(f"{name} {outcome}: {counts[outcome]} of {sum(counts.values())}")
