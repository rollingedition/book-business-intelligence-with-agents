"""Plot each layer set on the dev split's answer questions: context tokens against correct answers, with errors as a second
line. The printed lines are the points the prose rests on: each layer set's totals, and each added layer's step, which
the asserts check in the order the prose gives."""
from lib.context import LAYER_SETS, build_context, grade_with_context
from lib.figures import ACCENT, MUTED, new_figure, save
from lib.golden import load_golden
from lib.model import RecordedModel
from lib.warehouse import connect

con = connect()
model = RecordedModel("context-layers")
dev = [q for q in load_golden() if q.split == "dev" and q.kind == "answer"]   # the questions layer-ablation-dev scores
short = ("schema", "+columns", "+glossary", "+verified")                      # each layer set's name on the figure

tokens, correct, errors = [], [], []
for layers, name in zip(LAYER_SETS, short):
    outcomes = [grade_with_context(con, model, q, layers) for q in dev]      # graded as layer-ablation-dev grades them
    tokens.append(sum(build_context(con, q.question, layers).tokens for q in dev) // len(dev))   # mean context tokens
    correct.append(outcomes.count("correct"))
    errors.append(outcomes.count("error"))
    print(f"{name} context tokens: {tokens[-1]}\n{name} correct: {correct[-1]}\n{name} errors: {errors[-1]}")
print(f"dev answer questions: {len(dev)}")

# Each added layer's step: the difference from the layer set before it, on the same line of the output.
gain = [correct[i] - correct[i - 1] for i in range(1, 4)]    # correct answers the layer adds
step = [tokens[i] - tokens[i - 1] for i in range(1, 4)]      # context tokens the layer adds
for i, name in enumerate(short[1:]):
    print(f"{name} adds correct: {gain[i]}\n{name} adds context tokens: {step[i]}")
# Indexes: 0 is the column notes, 1 the glossary, 2 the verified queries.
assert gain[0] > gain[1] and gain[0] > gain[2], "the column notes gain the most correct answers"
assert gain[1] == 0, "the glossary adds no correct answers"
assert step[0] > step[1] > step[2], "the column notes add the most tokens, the verified queries the fewest"
assert gain[2] >= gain[0] - 1, "the verified queries gain nearly as many correct answers as the column notes"

fig, ax = new_figure(height=3.4)
ax.plot(tokens, correct, color=ACCENT, marker="o", label="correct answers")
ax.plot(tokens, errors, color=MUTED, linestyle="--", marker="o", markersize=4, label="errors (the query doesn't run)")
# Each label's offset in points, and its alignment. The glossary's flat segment runs into the label on its left, the
# dashed line runs under the column notes' error label to the right, and the schema's error point sits on the solid line.
place = {("correct", "+glossary"): ((0, 8), "center", "bottom"), ("errors", "schema"): ((-7, 0), "right", "center"),
         ("errors", "+columns"): ((0, 7), "center", "bottom")}
for series, values, color in (("correct", correct, ACCENT), ("errors", errors, MUTED)):
    for x, y, name in zip(tokens, values, short):
        (dx, dy), ha, va = place.get((series, name), ((-7, 0), "right", "center") if series == "correct" else ((7, 0), "left", "center"))
        ax.annotate(name, (x, y), textcoords="offset points", xytext=(dx, dy), ha=ha, va=va, color=color)
ax.set(xlim=(0, max(tokens) * 1.25), ylim=(-1, len(dev)), yticks=range(0, len(dev) + 1, 2),
       xlabel="context tokens per question, estimated (mean over the dev answer questions)", ylabel=f"answers out of {len(dev)}")
ax.legend(loc="upper left")
save(fig, "layers-correct-and-tokens")
