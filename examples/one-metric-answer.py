"""Answer the same question from one defined metric: the model picks the metric, the code writes and runs the SQL."""
from lib.agent import run_agent
from lib.golden import golden_result, load_golden, results_match
from lib.metrics import METRICS, NET_REVENUE
from lib.model import RecordedModel
from lib.prompts import metric_tools_prompt
from lib.tools import Toolbox
from lib.warehouse import connect

con = connect()
question = next(q for q in load_golden() if q.question_id == "gq-002")
print(f"metric: {NET_REVENUE.name}")
print(f"definition: {NET_REVENUE.description}")

system = metric_tools_prompt(METRICS.values())
trace = run_agent(question.question, system, RecordedModel("metric-tool-runs"), Toolbox(con))
answer = trace.answer
print(f"request: {trace.steps[0].arguments}")
print(answer.provenance.sql)
print(answer.show())
print(answer.provenance.describe())
print(f"matches golden: {results_match(answer.rows, golden_result(con, question))}")
