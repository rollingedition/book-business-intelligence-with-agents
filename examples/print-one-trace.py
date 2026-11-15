"""Print the trace of one recorded agent run: every model reply and tool result, then what the run returned. The `reason:` line printed last settles whether the decline's stated cause is true."""
from lib.agent import run_agent
from lib.golden import load_golden
from lib.metrics import METRICS
from lib.model import RecordedModel
from lib.prompts import metric_tools_prompt
from lib.tools import Toolbox
from lib.warehouse import connect

con = connect()
# gq-004: customers whose first order fell in fiscal 2026, which net_revenue can't count
question = next(q for q in load_golden() if q.question_id == "gq-004")
system = metric_tools_prompt(METRICS.values())
trace = run_agent(question.question, system, RecordedModel("metric-tool-runs"), Toolbox(con))

print(trace.show())
# each step is either a model reply or a tool result; this counts the replies
print(f"model calls: {sum(step.kind == 'model' for step in trace.steps)}")
print(f"answered: {trace.answer.answered}")
print(f"reason: {trace.answer.reason}")
