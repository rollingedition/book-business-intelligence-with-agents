"""Decline with a kind from a fixed list and a reason, so declines can be checked and counted like answers."""
from lib.agent import run_agent
from lib.declining import DECLINE_KINDS, MODEL_KINDS, DecliningToolbox, decline_kind
from lib.golden import load_golden
from lib.metric_tools import catalog
from lib.model import RecordedModel
from lib.prompts import declining_prompt
from lib.warehouse import connect

con = connect()
toolbox = DecliningToolbox(con)
for kind, meaning in DECLINE_KINDS.items():
    print(f"{kind}{' (model)' if kind in MODEL_KINDS else ' (code)'}: {meaning}")
print(toolbox.call("cannot_answer", {"reason": "no shipping costs"}).content)
print(toolbox.call("cannot_answer", {"kind": "not_in_data", "reason": "no shipping costs"}).answer.show())

system, model = declining_prompt(catalog(toolbox.layer)), RecordedModel("decline-runs")
for q in load_golden():
    if q.split == "dev" and q.kind == "decline" or q.question_id == "gq-016":
        trace = run_agent(q.question, system, model, DecliningToolbox(con, toolbox.layer, role=q.role), max_steps=4)
        calls = [step for step in trace.steps if step.kind == "model"]
        print(f"{q.question_id} ({q.decline_type or q.kind}): {q.question}")
        print(f"{q.question_id} ended with: {calls[-1].tool}, kind {decline_kind(trace.answer)}")
        print(f"{q.question_id} model calls: {len(calls)}")
        label = "asks" if trace.answer.provenance.source == "ask_back" else "reason"
        print(f"  {label}: {trace.answer.reason.splitlines()[0]}")
        if q.question_id == "gq-021":
            print(f"  first reply: {calls[0].content}")
        if q.question_id == "gq-020":
            asked = next(i for i, step in enumerate(trace.steps) if step.tool == "query_metric")
            request = trace.steps[asked].arguments
            print(f"gq-020 request: {', '.join(request['metrics'])} by {', '.join(request['group_by'])}, ordered by "
                  f"{', '.join(request['order_by'])}, period: {request.get('filters') or 'none'}")
            print(f"gq-020 check: {trace.steps[asked + 1].content}")
            print(f"gq-020 options: {', '.join(trace.steps[-2].arguments['options'])}")
