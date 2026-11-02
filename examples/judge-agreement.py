"""Calibrate the judge: its verdicts on the book's recorded answers against labels from results_match()."""
from lib.judge import agreement, answer_messages, kappa_one_verdict, parse_verdict, recorded_cases
from lib.model import RecordedModel
from lib.semantic import load
from lib.warehouse import connect

con, layer = connect(), load()
judge = RecordedModel("judge-verdicts")
cases, _ = recorded_cases(con, layer)          # every distinct answer with a number, with its reference label
judged = {c.case_id: parse_verdict(judge.complete(answer_messages(c.question, c.answer))) for c in cases}
verdicts = {case_id: v.label for case_id, v in judged.items()}
print(f"cases: {len(cases)}")
print(f"reference correct: {sum(c.reference == 'correct' for c in cases)}")
print(f"judge correct: {list(verdicts.values()).count('correct')}")
print(f"judge unparsed: {list(verdicts.values()).count('unparsed')}")
subsets = {"all": cases, "schema-only": [c for c in cases if c.case_id.endswith("schema-only")],
           "metric agents": [c for c in cases if not c.case_id.endswith("schema-only")]}
for name, subset in subsets.items():
    a = agreement([c.reference for c in subset], [verdicts[c.case_id] for c in subset])
    print(f"{name} cases: {a.n}")
    print(f"{name} cases the reference labels correct: {sum(c.reference == 'correct' for c in subset)}")
    print(f"{name} observed agreement: {a.observed:.2f}")
    print(f"{name} Cohen's kappa: {a.kappa:.2f}")
    print(f"{name} Scott's pi: {a.pi:.2f}")
    low, high = kappa_one_verdict([c.reference for c in subset], [verdicts[c.case_id] for c in subset])
    print(f"{name} kappa with any one verdict changed: {low:.2f} to {high:.2f}")
for reference, verdict, label in (("incorrect", "correct", "wrong answers the judge called correct"),
                                  ("correct", "incorrect", "right answers the judge called incorrect")):
    ids = [c.case_id for c in cases if c.reference == reference and verdicts[c.case_id] == verdict]
    print(f"{label}: {len(ids)} of {sum(c.reference == reference for c in cases)}")
    print(f"{label}, cases: {', '.join(ids)}")
# Read the reasons: how many rejections of right answers say a year's filter keeps only its first day?
first_day = [c.case_id for c in cases if c.reference == "correct" and judged[c.case_id].label == "incorrect"
             and any(w in judged[c.case_id].reason for w in ("January 1", "first day"))]
print(f"right answers rejected for reading a year's filter as January 1: {len(first_day)}")
