"""Score metrics-first against the schema-only baseline on both splits: dev for tuning, test once for the final number."""
from collections import Counter, defaultdict

from lib.agent import run_agent
from lib.golden import golden_result, grade, load_golden, schema_only_outcome
from lib.metric_tools import MetricToolbox, catalog
from lib.model import RecordedModel
from lib.prompts import metrics_first_prompt
from lib.semantic import load
from lib.warehouse import connect, describe_schema

con, layer = connect(), load()
schema, system = describe_schema(con), metrics_first_prompt(catalog(layer))
agent_model, sql_model = RecordedModel("metric-agent-runs"), RecordedModel("schema-only-sql")
counts, facts, missed = defaultdict(Counter), defaultdict(Counter), defaultdict(list)
for q in load_golden():
    toolbox = MetricToolbox(con, layer, role=q.role)
    trace = run_agent(q.question, system, agent_model, toolbox, max_steps=4)
    outcome = grade(q, trace.answer, golden_result(con, q))
    counts[q.split, "metrics-first"][outcome] += 1
    counts[q.split, "schema-only"][schema_only_outcome(con, sql_model, schema, q)] += 1
    facts[q.split][f"{q.kind} questions"] += 1
    facts[q.split][f"{q.kind} correct"] += outcome == "correct"
    facts[q.split]["forbidden answered"] += q.kind == "forbidden" and trace.answer.answered
    facts[q.split]["model calls"] += sum(step.kind == "model" for step in trace.steps)
    facts[q.split]["requests rejected"] += len(toolbox.rejected)
    facts[q.split]["correct after a rejection"] += bool(toolbox.rejected) and outcome == "correct"
    facts[q.split][f"asked back, {q.kind}"] += trace.answer.provenance.source == "ask_back"
    if outcome != "correct":
        missed[q.split].append(f"{q.question_id} {q.kind} {outcome}")

for split in ("dev", "test"):
    for approach in ("schema-only", "metrics-first"):     # only an agent run can hit the step limit
        for outcome in ("correct", "wrong", "error", "declined") + (("step limit",) if approach != "schema-only" else ()):
            print(f"{split} {approach} {outcome}: {counts[split, approach][outcome]} of 24")
    for kind in ("answer", "decline", "forbidden"):
        print(f"{split} metrics-first {kind} correct: {facts[split][kind + ' correct']} of {facts[split][kind + ' questions']}")
    for fact in ("forbidden answered", "model calls", "requests rejected", "correct after a rejection",
                 "asked back, answer", "asked back, decline", "asked back, forbidden"):
        print(f"{split} {fact}: {facts[split][fact]}")
    print(f"{split} not correct: {', '.join(missed[split])}")
