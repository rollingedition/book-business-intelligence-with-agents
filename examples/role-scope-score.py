"""Metrics-first on every golden question, as chapter 6 ran it and under each asker's policy, on both splits."""
from collections import Counter

from lib.agent import run_agent
from lib.golden import golden_result, grade, load_golden
from lib.metric_tools import MetricToolbox, catalog
from lib.model import RecordedModels
from lib.policies import PolicyLayer, PolicyToolbox, policy_for
from lib.prompts import metrics_first_prompt
from lib.semantic import load
from lib.warehouse import connect

con, layer = connect(), load()
model = RecordedModels("metric-agent-runs", "policy-agent-runs")   # this chapter recorded only the calls ch 6 lacks
counts, changed, declines = Counter(), [], []
for q in load_golden():
    seen_as = PolicyLayer(layer, policy_for(q.role, q.region or None), con)
    runs = {"no policy": (catalog(layer), MetricToolbox(con, layer, role=q.role)),
            "policy": (catalog(seen_as), PolicyToolbox(con, seen_as))}
    outcomes = {}
    for name, (listed, toolbox) in runs.items():
        trace = run_agent(q.question, metrics_first_prompt(listed), model, toolbox, max_steps=4)
        outcomes[name] = grade(q, trace.answer, golden_result(con, q))
        if name == "policy" and q.kind == "forbidden":
            by = "code" if (trace.answer.reason or "").startswith("forbidden") else "the model"
            declines.append(f"{q.question_id} ({q.role}), declined by {by}: {trace.answer.reason}")
        counts[q.split, name, q.kind] += outcomes[name] == "correct"
    counts[q.split, "questions", q.kind] += 1
    if outcomes["no policy"] != outcomes["policy"]:
        changed.append(f"{q.question_id} ({q.split}, {q.role}, {q.kind}): {outcomes['no policy']} -> "
                       f"{outcomes['policy']}")
for split in ("dev", "test"):
    for kind in ("answer", "decline", "forbidden"):
        for name in ("no policy", "policy"):
            print(f"{split} {kind} correct, {name}: {counts[split, name, kind]} of {counts[split, 'questions', kind]}")
print("changed by the policy:")
print("\n".join(changed))
print("\n".join(declines))
