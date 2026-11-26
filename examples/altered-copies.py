"""Run the golden SQL and the schema-only baseline's recorded SQL on the shop and on three copies, each altered in
one way, and print whether each query that matches on the shop still matches on each copy. The point rests on the
gq-031 lines: it matches on the shop and stops matching on the copy with one more large cancelled order, and the
asserts check that and that every other verdict holds."""
import duckdb

from lib.altered import copy_order, split_refund
from lib.golden import golden_result, load_golden, results_match
from lib.model import MissingRecording, RecordedModel
from lib.prompts import schema_only_messages
from lib.tools import extract_sql
from lib.warehouse import altered_copy, connect, describe_schema

shop = connect()
# each copy picks the row it changes with its own seed; the cancelled order is one of 2025's largest, 11 units or more
copies = {"duplicated order": altered_copy(copy_order("delivered", seed=1)),
          "cancelled order added": altered_copy(copy_order("cancelled", seed=2, units=11)),
          "refund split in two": altered_copy(split_refund(seed=3))}
model, schema = RecordedModel("schema-only-sql"), describe_schema(shop)
verdicts = {}
for q in load_golden():
    try:
        sql = extract_sql(model.complete(schema_only_messages(schema, q.question)))
        # the golden SQL runs again on each copy, so each copy has its own golden result
        match = {name: results_match(con.execute(sql).fetchall(), golden_result(con, q), q.order_matters, q.tolerance,
                                     q.absolute) for name, con in {"shop": shop, **copies}.items()}
    except (MissingRecording, duckdb.Error):   # a decline has no schema-only recording, and some of the model's SQL fails
        continue
    if match.pop("shop"):   # only a query that matches on the shop can stop matching on a copy
        verdicts[q.question_id] = match
        print(f"{q.question_id} still matches: " + ", ".join(f"{name} {'yes' if ok else 'no'}" for name, ok in match.items()))
    if q.question_id == "gq-031":   # units per order in 2025, on the shop and on the copy that exposes the model's SQL
        golds = []
        for name, con in [("shop", shop), ("cancelled order added", copies["cancelled order added"])]:
            golds.append(golden_result(con, q)[0][0])
            print(f"gq-031 model on {name}: {con.execute(sql).fetchone()[0]:.5f}")
            print(f"gq-031 golden on {name}: {golds[-1]:.4f}")
        assert golds[0] == golds[1]   # the gold leaves cancelled orders out, so the added one can't move it
# the model's units query keeps cancelled orders: it matches on the shop, and one more large one moves its average past
# the tolerance while the gold's stays
assert "gq-031" in verdicts and not verdicts["gq-031"]["cancelled order added"]
assert all(ok for qid, match in verdicts.items() for name, ok in match.items()
           if (qid, name) != ("gq-031", "cancelled order added"))   # no other query stops matching on any copy
