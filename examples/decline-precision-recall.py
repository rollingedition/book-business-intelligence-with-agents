"""Measure declines, not only accuracy: precision, recall, coverage, selective risk and a penalty score, on dev."""
from lib.agent import run_agent
from lib.declining import DecliningToolbox, Tally
from lib.golden import golden_result, grade, load_golden
from lib.metric_tools import MetricToolbox, catalog
from lib.model import RecordedModel
from lib.prompts import declining_prompt, metrics_first_prompt
from lib.semantic import load
from lib.warehouse import connect

con, layer = connect(), load()
agents = {"metrics-first": (metrics_first_prompt(catalog(layer)), RecordedModel("metric-agent-runs"), MetricToolbox),
          "declining": (declining_prompt(catalog(layer)), RecordedModel("decline-runs"), DecliningToolbox)}
# The dev split's answer and decline questions; forbidden questions are decided below the model, in chapter 9.
questions = [q for q in load_golden() if q.split == "dev" and q.kind in ("answer", "decline")]
for name, (system, model, Toolbox) in agents.items():
    tally, by_type = Tally(), {"ambiguous": Tally(), "unanswerable": Tally()}
    for q in questions:
        answer = run_agent(q.question, system, model, Toolbox(con, layer, role=q.role), max_steps=4).answer
        outcome = grade(q, answer, golden_result(con, q))
        tally.add(q.question_id, q.kind, answer, outcome)
        if q.kind == "decline":
            by_type[q.decline_type].add(q.question_id, q.kind, answer, outcome)
    for ending in ("right", "wrong", "abstained", "step limit"):
        print(f"{name} {ending}: {tally.count(ending=ending)} of {len(questions)}")
    for label, kind, ending in (("wrong numbers", None, "wrong"), ("declined answerable", "answer", "abstained")):
        ids = [i for i, k, e in tally.rows if kind in (None, k) and e == ending]
        print(f"{name} {label}: {', '.join(ids) or 'none'}")
    print(f"{name} decline precision: {tally.precision:.2f}")
    print(f"{name} decline recall: {tally.recall:.2f}")
    for kind, part in by_type.items():
        print(f"{name} recall, {kind}: {part.count('decline', 'abstained')} of {part.count('decline')}")
    print(f"{name} coverage: {tally.coverage:.2f}")
    print(f"{name} selective risk: {tally.selective_risk:.2f}")
    for c in (3, 10):
        print(f"{name} penalty score, c={c}: {tally.penalty_score(c):.2f}")
