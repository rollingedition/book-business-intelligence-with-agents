"""Plot what each cumulative layer set adds on the dev split's answer questions: prompt tokens against correct answers, with
errors as a second line. The printed lines are the points the prose rests on: each stack's tokens, correct and errors."""
from collections import Counter

from lib.context import LAYER_SETS, build_context, grade_with_context
from lib.figures import ACCENT, MUTED, new_figure, save
from lib.golden import load_golden
from lib.model import RecordedModel
from lib.warehouse import connect

con = connect()
model = RecordedModel("context-layers")
dev = [q for q in load_golden() if q.split == "dev" and q.kind == "answer"]   # the questions layer-ablation-dev scores
short = ("schema", "+columns", "+glossary", "+verified")                      # each stack's name on the figure

tokens, correct, errors = [], [], []
for layers, name in zip(LAYER_SETS, short):
    outcomes = Counter(grade_with_context(con, model, q, layers) for q in dev)   # graded as layer-ablation-dev grades them
    tokens.append(sum(build_context(con, q.question, layers).tokens for q in dev) // len(dev))   # mean prompt tokens, whole tokens
    correct.append(outcomes["correct"])
    errors.append(outcomes["error"])
    print(f"{name} tokens: {tokens[-1]}")
    print(f"{name} correct: {correct[-1]}")
    print(f"{name} errors: {errors[-1]}")
print(f"dev answer questions: {len(dev)}")

fig, ax = new_figure(height=3.4)
ax.plot(tokens, correct, color=ACCENT, marker="o", label="correct answers")
ax.plot(tokens, errors, color=MUTED, linestyle="--", marker="o", markersize=4, label="errors (the query doesn't run)")
for x, y, name in zip(tokens, correct, short):
    above = name == "+glossary"                                                   # its flat segment runs into the label on the left
    ax.annotate(name, (x, y), textcoords="offset points", xytext=(0, 8) if above else (-7, 0),
                ha="center" if above else "right", va="bottom" if above else "center", color=ACCENT)
for x, y, name in zip(tokens, errors, short):
    ax.annotate(name, (x, y), textcoords="offset points", xytext=(7, 0), ha="left", va="center", color=MUTED)
ax.set_xlim(0, 3400)
ax.set_ylim(-1, 17)
ax.set_yticks(range(0, 18, 2))
ax.set_xlabel("prompt tokens per question, estimated (mean over the dev answer questions)")
ax.set_ylabel(f"answers out of {len(dev)}")
ax.legend(loc="upper left")
save(fig, "layers-correct-and-tokens")
