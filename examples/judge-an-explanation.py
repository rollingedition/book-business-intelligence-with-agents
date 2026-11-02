"""Judge only what can't be compared: two reasons for declining the same question, shown in both orders."""
import re

from lib.judge import judge_pairs, recorded_cases
from lib.model import RecordedModel
from lib.semantic import load
from lib.warehouse import connect

con, layer = connect(), load()
_, pairs = recorded_cases(con, layer)
results = judge_pairs(RecordedModel("judge-verdicts"), pairs)
GROUPS = {"decline": "decline questions", "answer": "answerable questions both agents declined"}
AGENTS = ("metrics-first", "declining")
BLAMES_DATA = re.compile(r"\bdata (does not|doesn't) (include|contain)")
ALTERNATIVE = ("alternative", "instead", "reframe", "path forward")
for r in results:
    print(f"{r.case.question.question_id} ({r.case.question.kind}): metrics-first first -> {r.first.label}; "
          f"declining first -> {r.second.label}")
n = len(results)
print(f"pairs: {n}")
for group, name in GROUPS.items():
    print(f"pairs on {name}: {sum(r.case.question.kind == group for r in results)}")
print(f"same verdict in both orders: {sum(r.first.label == r.second_as_first for r in results)} of {n}")
print(f"first reason won in both orders: {sum(r.first.label == r.second.label == 'A' for r in results)} of {n}")
print(f"second reason won in both orders: {sum(r.first.label == r.second.label == 'B' for r in results)} of {n}")
for agent in AGENTS:
    print(f"{agent} reason won in both orders: {sum(r.winner == agent for r in results)}")
for group, name in GROUPS.items():
    for agent in AGENTS:
        print(f"{name}, {agent} reason won in both orders: "
              f"{sum(r.winner == agent and r.case.question.kind == group for r in results)}")
print(f"consistent winner was the longer reason: {sum(r.longer_won for r in results)}")
answerable = [r.case for r in results if r.case.question.kind == "answer"]
for agent, reasons in (("metrics-first", [c.first for c in answerable]), ("declining", [c.second for c in answerable])):
    said = sum(bool(BLAMES_DATA.search(x)) for x in reasons)
    print(f"answerable questions, {agent} reasons that say the data lacks it: {said} of {len(answerable)}")
replies = [v for r in results for v in (r.first, r.second)]
suggests = sum(any(w in v.reason.lower() for w in ALTERNATIVE) for v in replies)
print(f"judge replies that suggest an alternative or a reframe: {suggests} of {len(replies)}")
