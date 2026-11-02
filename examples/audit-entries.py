"""One audit entry per question: who asked, as which role, what the agent asked for, what ran and what came back."""
from lib.agent import run_agent
from lib.golden import load_golden
from lib.metric_tools import catalog
from lib.model import RecordedModel
from lib.policies import AuditLog, PolicyGuard, PolicyLayer, PolicyToolbox, policy_for
from lib.prompts import metrics_first_prompt
from lib.semantic import load
from lib.warehouse import agent_warehouse, connect

con, layer, log = connect(), load(), AuditLog()
golden = {q.question_id: q for q in load_golden()}
# Principals are made-up IDs; in production they come from the sign-in system, never from the question.
for principal, question_id in (("lead-emea-01", "gq-017"), ("lead-apac-01", "gq-024")):
    q = golden[question_id]
    policy = policy_for(q.role, q.region)
    seen_as = PolicyLayer(layer, policy, con)
    trace = run_agent(q.question, metrics_first_prompt(catalog(seen_as)), RecordedModel("metric-agent-runs"),
                      PolicyToolbox(con, seen_as), max_steps=4)
    log.record(principal, policy, q.question, trace.answer, request=trace.steps[-2].arguments)

finance = policy_for("finance")
agent_sql = "SELECT count(*) AS n FROM analytics.dim_customers WHERE email LIKE 'customer-0004%'"
answer = PolicyGuard(agent_warehouse(con, policy=finance), policy=finance).run(agent_sql)
log.record("finance-03", finance, "How many customers have an email starting customer-0004?", answer,
           agent_sql=agent_sql)

print(log.jsonl())
print(f"entries: {len(log.entries)}")
print(f"declined as forbidden: {sum((e['reason'] or '').startswith('forbidden') for e in log.entries)}")
