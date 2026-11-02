"""Five runs of 12 dev questions per agent, one per seed: how much a score moves, and which questions flip."""
from lib.golden import load_golden
from lib.model import RecordedModel
from lib.regressions import ORIGINAL_SEED, SeededRecording, replay
from lib.semantic import load
from lib.warehouse import connect

con, layer = connect(), load()
QUESTIONS = ("gq-001", "gq-002", "gq-003", "gq-004", "gq-005", "gq-007", "gq-008", "gq-012", "gq-016", "gq-017",
             "gq-018", "gq-020")                         # the 12 questions repeat-runs holds
questions = [q for q in load_golden() if q.question_id in QUESTIONS]
seeds = (ORIGINAL_SEED, 1, 2, 3, 4)                      # 2718 replays the original recordings
for agent in ("metrics-first", "declining"):
    per_question = {q.question_id: 0 for q in questions}
    scores = []
    for seed in seeds:
        runs = replay(con, layer, agent, questions, seed=seed)
        scores.append(sum(r.outcome == "correct" for r in runs))
        for r in runs:
            per_question[r.question.question_id] += r.outcome == "correct"
        print(f"{agent} seed {seed}: {scores[-1]} of {len(questions)} correct")
    spread = f"{min(scores)} to {max(scores)}" if min(scores) < max(scores) else f"{min(scores)} at every seed"
    print(f"{agent} correct across seeds: {spread}")
    flips = [f"{q} ({n} of 5)" for q, n in per_question.items() if 0 < n < 5]
    print(f"{agent} questions that flip: {len(flips)}")
    print(f"{agent} flipping: {', '.join(flips)}")
    print(f"{agent} always correct: {sum(n == 5 for n in per_question.values())}")
    print(f"{agent} never correct: {sum(n == 0 for n in per_question.values())}")

# Does a run replay byte for byte? The declining agent ran again with seed 2718; compare it with decline-runs.
again, original = SeededRecording("declining", ORIGINAL_SEED).calls, RecordedModel("decline-runs").calls
same = sum(key in original and call["reply"] == original[key]["reply"] for key, call in again.items())
print(f"seed {ORIGINAL_SEED} again: {same} of {len(again)} calls identical to decline-runs")
