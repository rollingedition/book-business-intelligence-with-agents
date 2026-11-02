"""gq-017, asked by EMEA's regional lead, on both of the agent's paths: without the policy, then with it."""
import re
from dataclasses import replace

from lib.agent import run_agent
from lib.context import LAYERS, build_context
from lib.golden import golden_result, grade, load_golden
from lib.metric_tools import MetricToolbox, catalog
from lib.model import RecordedModel, RecordedModels
from lib.policies import PolicyGuard, PolicyLayer, PolicyToolbox, policy_for
from lib.prompts import layered_sql_messages, metrics_first_prompt
from lib.semantic import load
from lib.sql_guard import SqlGuard, answer_with_repair
from lib.warehouse import agent_warehouse, connect

q = next(q for q in load_golden() if q.question_id == "gq-017")
con, layer, policy = connect(), load(), policy_for(q.role, q.region)
print(f"question: {q.question} ({q.role}, {q.region})")

# Metrics first (chapter 6): the same recorded request, through the layer as it is and as the lead sees it.
for name, toolbox in (("metric, no policy", MetricToolbox(con, layer, role=q.role)),
                      ("metric, policy", PolicyToolbox(con, PolicyLayer(layer, policy, con)))):
    trace = run_agent(q.question, metrics_first_prompt(catalog(layer)), RecordedModel("metric-agent-runs"), toolbox,
                      max_steps=4)
    print(f"{name}, outcome: {grade(q, trace.answer, golden_result(con, q))}")
    print(f"{name}, countries: {', '.join(row[0] for row in trace.answer.rows)}")
print(f"request: {trace.steps[-2].arguments}")
print(f"metric, policy, provenance filters: {trace.answer.provenance.filters}")
# The subquery lists all 15 columns of fct_orders; they're shortened to "..." here.
print(re.sub(r'SELECT\s+"order_id".*?FROM', "SELECT ... FROM", trace.answer.provenance.sql, flags=re.S))

# Guarded SQL (chapter 7): the recorded layered SQL and its one repair, through each guard.
messages = layered_sql_messages(build_context(con, q.question, LAYERS).text, q.question)
sessions = "SELECT count(*) - count(customer_id) FROM analytics.fct_sessions"   # sessions with no region
for name, guard in (("SQL, no policy", SqlGuard(agent := agent_warehouse(con))),   # every allowed mart, whole
                    ("SQL, policy", PolicyGuard(agent_warehouse(con, policy=policy), policy=policy))):  # EMEA only
    run = answer_with_repair(guard, RecordedModels("context-layers", "guarded-sql-runs"), messages, q.question, q.role)
    print(f"{name}, outcome: {grade(q, run.answer, golden_result(con, q))}")
    print(f"{name}, countries: {len(run.answer.rows)}")
    print(f"{name}, sessions with no customer: {guard.run(sessions).rows[0][0]}")

# Deny by default: with the sessions filter taken out of the lead's policy, the guard's allowlist drops the table.
unwritten = replace(policy, row_filters={t: f for t, f in policy.row_filters.items() if t != "analytics.fct_sessions"})
readable = unwritten.allowed_schema(agent)["analytics"]
print(f"sessions with no row filter written: {'allowed' if 'fct_sessions' in readable else 'refused'}")
