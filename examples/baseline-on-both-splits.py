"""The baseline every later chapter must beat: schema-only SQL scored on the dev split and on the held-out test split.
The prose's split counts are the per-split lines, and its declines, forbidden and answer counts the last three lines."""
from collections import Counter

from lib.golden import load_golden, schema_only_outcome
from lib.model import RecordedModel
from lib.warehouse import connect, describe_schema

con = connect()
schema, model = describe_schema(con), RecordedModel("schema-only-sql")
outcomes = {"dev": Counter(), "test": Counter()}
by_kind = Counter()
for q in load_golden():
    outcome = schema_only_outcome(con, model, schema, q)
    outcomes[q.split][outcome] += 1
    by_kind[q.kind, outcome == "correct"] += 1  # (kind, correct) pairs, counted over both splits

for split, counts in outcomes.items():
    total = sum(counts.values())
    for outcome in ("correct", "wrong", "error", "declined"):  # "error" when the SQL fails; grade() gives the rest
        print(f"{split} {outcome}: {counts[outcome]} of {total}")
    print(f"{split} accuracy: {counts['correct'] / total:.1%}")
for kind in ("answer", "decline", "forbidden"):
    print(f"{kind} correct, both splits: {by_kind[kind, True]} of {by_kind[kind, True] + by_kind[kind, False]}")
