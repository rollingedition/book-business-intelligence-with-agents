"""The dev questions that stay wrong with all four layers: each one's query, and whether gq-007 fails only on spelling."""
import duckdb
from lib.context import LAYERS, build_context, grade_with_context
from lib.golden import golden_result, grade, load_golden
from lib.model import RecordedModel
from lib.prompts import layered_sql_messages
from lib.tools import extract_sql, run_sql
from lib.warehouse import connect

con, model = connect(), RecordedModel("context-layers")
dev = [q for q in load_golden() if q.split == "dev" and q.kind == "answer"]


def sql_with_all_layers(q):
    return extract_sql(model.complete(layered_sql_messages(build_context(con, q.question, LAYERS).text, q.question)))


unsolved = [(q, outcome) for q in dev if (outcome := grade_with_context(con, model, q, LAYERS)) != "correct"]
print(f"not correct with all four layers: {len(unsolved)}")
for q, outcome in unsolved:
    sql = sql_with_all_layers(q)
    print(f"{q.question_id} ({outcome}): {q.question}")
    print("\n".join("    " + line for line in sql.strip().splitlines()))
    if outcome == "error":
        try:
            run_sql(con, sql)
        except duckdb.Error as e:
            print(f"    -- {str(e).splitlines()[0]}")

gq007 = next(q for q in dev if q.question_id == "gq-007")
respelled = sql_with_all_layers(gq007).replace("'tents'", "'Tents'")
print(f"gq-007 with 'Tents' spelled as stored: {grade(gq007, run_sql(con, respelled), golden_result(con, gq007))}")
