"""Repair once from the guard's message: how often one repair turns a refusal into an answer on the dev split, and two
repairs in full. The counts are the figures the prose quotes; the repaired SQL is printed for the reader to check."""
from collections import Counter

from lib.context import LAYERS, build_context
from lib.golden import golden_result, grade, load_golden
from lib.model import RecordedModels
from lib.prompts import layered_sql_messages, schema_only_messages
from lib.sql_guard import SqlGuard, answer_with_repair
from lib.warehouse import agent_warehouse, connect, describe_schema

con = connect()
guard, schema = SqlGuard(agent_warehouse(con)), describe_schema(con)
# First replies from chapters 1 and 4's recordings; each repair reply from this chapter's.
model = RecordedModels("schema-only-sql", "context-layers", "guarded-sql-runs")
MESSAGES = {"schema-only": lambda q: schema_only_messages(schema, q.question),
            "layered": lambda q: layered_sql_messages(build_context(con, q.question, LAYERS).text, q.question)}
dev = [q for q in load_golden() if q.split == "dev" and q.kind == "answer"]
shown = {}

for context, messages in MESSAGES.items():
    counts = Counter()
    for q in dev:
        run = answer_with_repair(guard, model, messages(q), q.question, role=q.role, repairs=1)
        outcome = grade(q, run.answer, golden_result(con, q))
        when = "after repair" if run.repaired else "first time"
        counts[f"ran {when}"] += run.attempts[-1].outcome == "ran"
        counts[f"correct {when}"] += outcome == "correct"
        counts[f"wrong {when}"] += outcome == "wrong"
        counts["refused or failed first"] += run.repaired
        counts["declined after repair"] += run.attempts[-1].outcome == "declined"
        shown[context, q.question_id] = run
    print(f"{context}, questions: {len(dev)}")
    for key in ("ran first time", "correct first time", "wrong first time", "refused or failed first",
                "ran after repair", "correct after repair", "wrong after repair", "declined after repair"):
        print(f"{context}, {key}: {counts[key]}")

for context, question_id in (("layered", "gq-017"), ("schema-only", "gq-001")):
    run = shown[context, question_id]
    print(f"{question_id} {context}, refused: {run.attempts[0].message.split('. The tables')[0]}")   # the refusal, without its list of tables
    print(run.attempts[1].sql)                       # attempt 0 is the first reply, attempt 1 the repair
    rows = len(run.answer.rows)
    print(f"{question_id} {context}, after repair: {run.attempts[1].outcome} and returned {rows} row{'s' * (rows != 1)}")
