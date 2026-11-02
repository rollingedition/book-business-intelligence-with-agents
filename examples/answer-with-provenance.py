"""Show the provenance with every answer: the metric's definition, filters, role, freshness and the SQL that ran."""
from lib.agent import run_agent
from lib.declining import DecliningToolbox, provenance_card
from lib.golden import golden_result, grade, load_golden
from lib.metric_tools import catalog
from lib.model import RecordedModel
from lib.prompts import declining_prompt
from lib.semantic import load
from lib.warehouse import connect

con, layer = connect(), load()
system, model = declining_prompt(catalog(layer)), RecordedModel("decline-runs")
golden = {q.question_id: q for q in load_golden()}
for question_id in ("gq-002", "gq-012", "gq-021"):
    q = golden[question_id]
    toolbox = DecliningToolbox(con, layer, role=q.role)
    trace = run_agent(q.question, system, model, toolbox, max_steps=4)
    print(f"{question_id}: {q.question}")
    print(provenance_card(trace.answer, layer, toolbox.freshness, sql=question_id == "gq-002"))
    print(f"{question_id} outcome: {grade(q, trace.answer, golden_result(con, q))}")
    print()
