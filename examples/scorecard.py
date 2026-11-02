"""Score the book's agents on more than accuracy: dev to compare them, and the held-out test split once, at the end."""
from lib.golden import load_golden
from lib.regressions import Scorecard, replay
from lib.semantic import load
from lib.warehouse import connect

con, layer = connect(), load()
# Answer and decline questions; forbidden questions are decided below the model, by chapter 9's policies.
questions = [q for q in load_golden() if q.kind in ("answer", "decline")]
for split in ("dev", "test"):
    in_split = [q for q in questions if q.split == split]
    print(f"{split} questions: {len(in_split)}")
    runs = {agent: replay(con, layer, agent, in_split) for agent in ("schema-only", "metrics-first", "declining")}
    for agent, agent_runs in runs.items():
        print("\n".join(Scorecard(agent_runs).lines(f"{split} {agent}")))
    for label, was, now in (("fixed", False, True), ("broken", True, False)):
        ids = [a.question.question_id for a, b in zip(runs["metrics-first"], runs["declining"])
               if (a.outcome == "correct") == was and (b.outcome == "correct") == now]
        print(f"{split} {label} by the declining prompt: {', '.join(ids) or 'none'}")
