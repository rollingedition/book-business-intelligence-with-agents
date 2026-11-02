"""Guarded SQL on the long tail, the answer questions no metric in the semantic layer covers; then one promoted."""
import shutil
import tempfile
from collections import Counter
from pathlib import Path

from lib.answers import format_value
from lib.context import LAYERS, build_context
from lib.golden import golden_result, grade, load_golden, results_match
from lib.model import RecordedModels
from lib.prompts import layered_sql_messages
from lib.semantic import SEMANTIC_DIR, MetricRequest, load
from lib.sql_guard import SqlGuard, answer_with_repair
from lib.warehouse import agent_warehouse, connect

LONG_TAIL = {"gq-007": "a filter on what an order contains", "gq-016": "customers with an order",
             "gq-031": "units per order", "gq-032": "gross margin", "gq-033": "session conversion",
             "gq-034": "marketing spend", "gq-036": "one order's refunds", "gq-037": "duplicate sign-ups",
             "gq-038": "a weekday dimension", "gq-041": "discount"}
con, golden = connect(), {q.question_id: q for q in load_golden()}
guard, model = SqlGuard(agent_warehouse(con)), RecordedModels("context-layers", "context-layers-test", "guarded-sql-runs")
counts = Counter()
for question_id, needs in LONG_TAIL.items():
    q = golden[question_id]
    run = answer_with_repair(guard, model, layered_sql_messages(build_context(con, q.question, LAYERS).text,
                                                                 q.question), q.question, role=q.role)
    outcome = grade(q, run.answer, gold := golden_result(con, q))
    counts[q.split, outcome] += 1
    print(f"{question_id} ({q.split}, {needs}): {outcome}, after {' then '.join(a.outcome for a in run.attempts)}")
    if outcome == "wrong":
        row = ", ".join(map(format_value, min(run.answer.rows))) if run.answer.rows else "no rows"
        print(f"{question_id} first row: {row} (golden: {', '.join(map(format_value, min(gold)))})")
print(*(f"long tail questions on {s}: {sum(golden[i].split == s for i in LONG_TAIL)}" for s in ("dev", "test")), sep="\n")
for split, outcome in [(s, o) for s in ("dev", "test") for o in ("correct", "wrong", "declined")]:
    print(f"long tail {split} {outcome}: {counts[split, outcome]} of {sum(n for (s, _), n in counts.items() if s == split)}")

with tempfile.TemporaryDirectory() as folder:        # promote gq-038: one dimension added to a copy of the YAML
    shutil.copytree(SEMANTIC_DIR, copy := Path(folder) / "semantic")
    with open(copy / "orders.yml", "a") as orders:
        orders.write("    - name: weekday\n      type: categorical\n      expr: dayname(order_date_local)\n")
    layer = load(copy)
answer = layer.query(con, MetricRequest(("net_revenue", "orders"), ("order__weekday",), {"metric_time__year": 2025}))
print("gq-038 as a metric request matches golden:", results_match(answer.rows, golden_result(con, golden["gq-038"])))
