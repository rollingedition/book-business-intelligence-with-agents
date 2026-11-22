"""Draw each approach's outcomes on each split as bars of 24 golden questions: correct, wrong, error, declined and step limit.
The prose rests on the printed count of each outcome per bar, graded as metrics-first-score grades them. Declined counts
answerable questions the run left unanswered, declined or asked back; declining a question that should be declined is correct."""
import lib  # noqa: F401  (first, so threads and seeds are fixed before any numerical library loads)
from collections import Counter, defaultdict

from matplotlib.patches import Patch

from lib.agent import run_agent
from lib.figures import ACCENT, INK, MUTED, RULE, new_figure, save
from lib.golden import golden_result, grade, load_golden, schema_only_outcome
from lib.metric_tools import MetricToolbox, catalog
from lib.model import RecordedModel
from lib.prompts import metrics_first_prompt
from lib.semantic import load
from lib.warehouse import connect, describe_schema

con, layer = connect(), load()
schema, system = describe_schema(con), metrics_first_prompt(catalog(layer))
agent_model, sql_model = RecordedModel("metric-agent-runs"), RecordedModel("schema-only-sql")
counts = defaultdict(Counter)
for q in load_golden():
    trace = run_agent(q.question, system, agent_model, MetricToolbox(con, layer, role=q.role), max_steps=4)  # four calls at most
    counts[q.split, "metrics-first"][grade(q, trace.answer, golden_result(con, q))] += 1
    counts[q.split, "schema-only"][schema_only_outcome(con, sql_model, schema, q)] += 1

# Each outcome has a colour and a line hatch, so the legend tells them apart without colour; drawn left to right.
OUTCOMES = (("correct", ACCENT, None, ACCENT), ("wrong", INK, "/", RULE), ("error", MUTED, "-", RULE),
            ("declined", RULE, "\\", MUTED), ("step limit", "none", "x", INK))
ROWS = [(split, approach) for split in ("dev", "test") for approach in ("schema-only", "metrics-first")]
for split, approach in ROWS:
    for outcome, *_ in OUTCOMES:
        print(f"{split} {approach} {outcome}: {counts[split, approach][outcome]}")
    assert sum(counts[split, approach].values()) == 24, f"{split} {approach} does not hold 24 questions"

fig, ax = new_figure(height=3.4)
# Bars are placed by height from the bottom, so the first row is counted from the top: y runs from the last row down to 0.
for y, (split, approach) in zip(range(len(ROWS))[::-1], ROWS):
    left = 0
    for outcome, face, hatch, edge in OUTCOMES:
        n = counts[split, approach][outcome]
        if n:                                  # a zero count draws no segment
            ax.barh(y, n, left=left, height=0.6, facecolor=face, hatch=hatch, edgecolor=edge, linewidth=0.8)
        left += n
ax.set_yticks(range(len(ROWS))[::-1], [f"{approach}, {split} split" for split, approach in ROWS])
ax.set(xlim=(0, 24), xticks=range(0, 25, 4), xlabel="golden questions out of 24 on the split")
ax.grid(axis="y", visible=False)
handles = [Patch(facecolor=f, edgecolor=e, hatch=h, label=o) for o, f, h, e in OUTCOMES]
ax.legend(handles=handles, loc="lower left", bbox_to_anchor=(0, 1.02), ncol=3, handlelength=2.2)
save(fig, "outcomes-by-approach")
