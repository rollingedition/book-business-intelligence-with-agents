"""Gate a prompt change on paired, per-question differences over five recorded runs of each question."""
from lib.golden import load_golden
from lib.regressions import ORIGINAL_SEED, Comparison, gate, replay, smallest_detectable, t_quantile
from lib.semantic import load
from lib.warehouse import connect

con, layer = connect(), load()
QUESTIONS = ("gq-001", "gq-002", "gq-003", "gq-004", "gq-005", "gq-007", "gq-008", "gq-012", "gq-016", "gq-017",
             "gq-018", "gq-020")                         # the 12 questions repeat-runs holds
questions = [q for q in load_golden() if q.question_id in QUESTIONS]
seeds = (ORIGINAL_SEED, 1, 2, 3, 4)
correct = {agent: {q.question_id: [] for q in questions} for agent in ("metrics-first", "declining")}
for agent, runs in correct.items():
    for seed in seeds:
        for run in replay(con, layer, agent, questions, seed=seed):
            runs[run.question.question_id].append(run.outcome == "correct")

# One run each, as a CI job that runs every question once would see it.
once = Comparison({q: r[:1] for q, r in correct["metrics-first"].items()},
                  {q: r[:1] for q, r in correct["declining"].items()})
fixed, broken = once.moved()
print(f"one run: fixed {len(fixed)} ({', '.join(fixed)}), broken {len(broken)} ({', '.join(broken)})")
print(f"one run sign test p: {once.sign_test():.2f}")
print(f"one run stable breaks: {', '.join(once.stable_breaks()) or 'none'}")   # with one run, every flip is "stable"

five = Comparison(correct["metrics-first"], correct["declining"])
for q in five.questions:
    print(f"{q}: metrics-first {sum(five.base[q])} of 5, declining {sum(five.candidate[q])} of 5")
fixed, broken = five.moved()
print(f"five runs: fixed {len(fixed)} ({', '.join(fixed) or 'none'}), broken {len(broken)} ({', '.join(broken) or 'none'})")
low, high = five.interval()
print(f"five runs mean paired difference: {five.mean_difference:+.2f}")
print(f"five runs 95% interval: {low:+.2f} to {high:+.2f}")
print(f"t multiplier, {len(five.questions) - 1} degrees of freedom: {t_quantile(0.975, len(five.questions) - 1):.2f}")
print(f"five runs interval half-width: {five.half_width():.2f}")
k = smallest_detectable(len(five.questions))
print(f"fewest clean flips the mean rule detects: {k} of {len(five.questions)}")
print(f"smallest mean change the mean rule detects: {k / len(five.questions):.2f}")
print(f"five runs sign test p: {five.sign_test():.2f}")
passed, reasons = gate(five)
print(f"gate: {'pass' if passed else 'fail'}")
print("\n".join(f"gate reason: {r}" for r in reasons))
