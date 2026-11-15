"""Add the business glossary on top of the column notes, and count what it changes on the dev questions. The gq-002
lines show the query the prose describes: with the glossary, the March query no longer filters on status."""
from lib.context import LAYER_SETS, build_context, grade_with_context, load_glossary
from lib.golden import load_golden
from lib.model import RecordedModel
from lib.prompts import layered_sql_messages
from lib.warehouse import connect

con = connect()
terms = load_glossary()
print(f"glossary terms: {len(terms)}")
print(f"glossary tokens (estimated): {build_context(con, '', layers=('glossary',)).tokens}")
print(next(t for t in terms if t.startswith("revenue:")))

model = RecordedModel("context-layers")
before, after = LAYER_SETS[1], LAYER_SETS[2]          # schema and column notes; then the glossary too
dev = [q for q in load_golden() if q.split == "dev" and q.kind == "answer"]
changes = {(was, now): [] for was in ("correct", "other") for now in ("correct", "other")}   # "other" is wrong or error
for q in dev:
    was, now = (grade_with_context(con, model, q, layers) for layers in (before, after))
    changes["correct" if was == "correct" else "other", "correct" if now == "correct" else "other"].append(q.question_id)
print(f"fixed by the glossary: {len(changes['other', 'correct'])} ({', '.join(changes['other', 'correct'])})")
print(f"broken by the glossary: {len(changes['correct', 'other'])} ({', '.join(changes['correct', 'other'])})")

q = next(q for q in dev if q.question_id == "gq-002")
reply = model.complete(layered_sql_messages(build_context(con, q.question, after).text, q.question))
filters_status = "status" in reply     # a query that filters on status has to name the column
assert not filters_status              # the chapter states it: with the glossary, gq-002 no longer filters on status
print(f"gq-002 with the glossary filters status: {'yes' if filters_status else 'no'}")
