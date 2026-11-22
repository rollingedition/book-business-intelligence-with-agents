"""Draw each agent's accuracy on each split with its 95% Wilson interval, scored as scorecard.py scores it.
The prose rests on the printed bounds and on the yes or no lines: the dev intervals of schema-only SQL and the metric agents
are clear of each other, the test intervals of schema-only SQL and metrics-first overlap, and metrics-first's and declining's dev intervals are equal."""
import lib  # noqa: F401  (first, so threads and seeds are fixed before any numerical library loads)
from matplotlib.lines import Line2D

from lib.figures import INK, MUTED, new_figure, save
from lib.golden import load_golden
from lib.regressions import Scorecard, replay
from lib.semantic import load
from lib.warehouse import connect

con, layer = connect(), load()
# The answer and decline questions of each split, selected as scorecard.py selects them.
questions = [q for q in load_golden() if q.kind in ("answer", "decline")]
AGENTS, SPLITS = ("schema-only", "metrics-first", "declining"), ("dev", "test")
cards, iv = {}, {}                                 # iv holds each (low, high) interval
for split in SPLITS:
    in_split = [q for q in questions if q.split == split]
    for agent in AGENTS:
        card = Scorecard(replay(con, layer, agent, in_split))
        cards[split, agent] = (card.accuracy, *card.interval)   # the Wilson interval, at about 95%
        iv[split, agent] = card.interval

dev_s, dev_m, dev_d = iv["dev", "schema-only"], iv["dev", "metrics-first"], iv["dev", "declining"]
test_s, test_m = iv["test", "schema-only"], iv["test", "metrics-first"]
print(f"dev schema-only interval high: {dev_s[1]:.2f}")
print(f"dev metrics-first interval low: {dev_m[0]:.2f}")
print(f"test schema-only interval high: {test_s[1]:.2f}")
print(f"test metrics-first interval low: {test_m[0]:.2f}")
checks = {  # each claim the prose makes, printed as a word and asserted
    "dev schema-only interval clear of metrics-first": dev_s[1] < dev_m[0],
    "dev schema-only interval clear of declining": dev_s[1] < dev_d[0],
    "test schema-only and metrics-first intervals overlap": test_s[0] <= test_m[1] and test_m[0] <= test_s[1],
    "dev metrics-first and declining intervals equal": (round(dev_m[0], 2), round(dev_m[1], 2))
                                                        == (round(dev_d[0], 2), round(dev_d[1], 2)),
}
for name, ok in checks.items():
    print(f"{name}: {'yes' if ok else 'no'}")
    assert ok, name

fig, ax = new_figure(height=3.2)
rows = range(len(AGENTS))[::-1]                    # the first agent is drawn at the top
SHAPES = {"dev": ("o", INK), "test": ("s", MUTED)}  # each split has its own marker shape and tone
for y, agent in zip(rows, AGENTS):
    for split, offset in (("dev", 0.15), ("test", -0.15)):   # dev above the row, test below, so the two bars stay apart
        accuracy, low, high = cards[split, agent]
        marker, color = SHAPES[split]
        ax.errorbar(accuracy, y + offset, xerr=[[accuracy - low], [high - accuracy]], fmt=marker, color=color,
                    markersize=6, capsize=3, elinewidth=1.4)
ax.set_yticks(rows, ["schema-only SQL", "metrics-first", "declining"])
ax.set(ylim=(-0.5, len(AGENTS) - 0.5), xlim=(0, 1), xlabel="accuracy on the split's questions, with its 95% interval")
handles = [Line2D([], [], marker=m, color=c, linestyle="none", label=f"{s} split") for s, (m, c) in SHAPES.items()]
ax.legend(handles=handles, loc="lower left", bbox_to_anchor=(0, 1.02), ncol=2)
save(fig, "accuracy-intervals")
