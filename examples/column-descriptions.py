"""Add notes on columns whose names mislead, and see which dev questions the recorded model now gets right."""
from lib.context import LAYER_SETS, build_context, grade_with_context, load_column_notes
from lib.golden import load_golden
from lib.model import RecordedModel
from lib.warehouse import connect

con = connect()
notes = load_column_notes()
print(f"column notes: {len(notes)}")
print(f"column notes tokens (estimated): {build_context(con, '', layers=('columns',)).tokens}")
for note in notes:
    if note.startswith(("analytics.fct_orders.status", "analytics.fct_orders.placed_at")):
        print(note)

model = RecordedModel("context-layers")
before, after = LAYER_SETS[0], LAYER_SETS[1]          # schema; schema and column notes
dev = [q for q in load_golden() if q.split == "dev" and q.kind == "answer"]
fixed, broken = [], []
for q in dev:
    was, now = grade_with_context(con, model, q, before), grade_with_context(con, model, q, after)
    if was != "correct" and now == "correct":
        fixed.append(q.question_id)
    if was == "correct" and now != "correct":
        broken.append(q.question_id)
print(f"fixed by column notes: {len(fixed)} ({', '.join(fixed)})")
print(f"broken by column notes: {len(broken)} ({', '.join(broken)})")
