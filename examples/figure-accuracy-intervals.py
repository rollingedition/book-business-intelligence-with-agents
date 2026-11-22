"""Draw each agent's accuracy on each split with its 95% Wilson interval, scored as scorecard.py scores it.
The prose rests on the printed bounds and on the yes or no lines: on dev, schema-only SQL's interval is clear of both metric
agents', and metrics-first's and declining's dev intervals are equal."""
import lib  # noqa: F401  (first, so threads and seeds are fixed before any numerical library loads)
from lib.figures import INK, MUTED, new_figure, save
from lib.golden import load_golden
from lib.regressions import Scorecard, replay
from lib.semantic import load
from lib.warehouse import connect

con, layer = connect(), load()
AGENTS, SPLITS = ("schema-only", "metrics-first", "declining"), ("dev", "test")
cards = {}                                    # (accuracy, low, high) per split and agent
for split in SPLITS:
    in_split = [q for q in load_golden() if q.split == split and q.kind in ("answer", "decline")]  # as scorecard.py selects them
    for agent in AGENTS:
        card = Scorecard(replay(con, layer, agent, in_split))
        cards[split, agent] = (card.accuracy, *card.interval)              # the Wilson interval, at about 95%
d_s, d_m, d_d = cards["dev", "schema-only"], cards["dev", "metrics-first"], cards["dev", "declining"]
print(f"dev schema-only interval high: {d_s[2]:.2f}")
print(f"dev metrics-first interval low: {d_m[1]:.2f}")
checks = {  # each claim the prose makes, printed as a word and asserted
    "dev schema-only interval clear of metrics-first": d_s[2] < d_m[1],
    "dev schema-only interval clear of declining": d_s[2] < d_d[1],
    "dev metrics-first and declining intervals equal": d_m[1:] == d_d[1:],
}
for name, ok in checks.items():
    print(f"{name}: {'yes' if ok else 'no'}")
    assert ok, name

fig, ax = new_figure(height=3.2)
for y, agent in zip(range(len(AGENTS))[::-1], AGENTS):    # the first agent is drawn at the top
    for split, offset in (("dev", 0.15), ("test", -0.15)):    # dev above the row, test below, so the bars stay apart
        accuracy, lo, hi = cards[split, agent]
        ax.errorbar(accuracy, y + offset, xerr=[[accuracy - lo], [hi - accuracy]], fmt="o" if split == "dev" else "s",
                    color=INK if split == "dev" else MUTED, markersize=6, capsize=3, elinewidth=1.4,
                    label=f"{split} split" if agent == AGENTS[0] else None)   # one legend entry per split
ax.set_yticks(range(len(AGENTS))[::-1], ["schema-only SQL", "metrics-first", "declining"])
ax.set(ylim=(-0.5, len(AGENTS) - 0.5), xlim=(0, 1), xlabel="accuracy on the split's questions, with its 95% interval")
ax.legend(loc="lower left", bbox_to_anchor=(0, 1.02), ncol=2)
save(fig, "accuracy-intervals")
