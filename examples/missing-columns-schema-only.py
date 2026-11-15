"""Why the dev queries written with the schema alone don't run: the column each one names, and the analytics tables that have it.
The per-table counts are the evidence the prose rests on: every failure is a column on the wrong table."""
import re
from collections import Counter

import duckdb
from lib.context import LAYER_SETS, build_context
from lib.golden import load_golden
from lib.model import RecordedModel
from lib.prompts import layered_sql_messages
from lib.tools import extract_sql, run_sql
from lib.warehouse import connect

con, model = connect(), RecordedModel("context-layers")
dev = [q for q in load_golden() if q.split == "dev" and q.kind == "answer"]
where = Counter()
for q in dev:
    context = build_context(con, q.question, LAYER_SETS[0])          # the schema alone
    sql = extract_sql(model.complete(layered_sql_messages(context.text, q.question)))
    try:
        run_sql(con, sql)
        continue
    except duckdb.Error as e:
        column = re.search(r'column (?:named )?"(\w+)"', str(e)).group(1)   # DuckDB says either form; take the name
    (tables,), = con.execute(
        "SELECT string_agg(table_schema || '.' || table_name, ', ' ORDER BY 1) FROM information_schema.columns "   # sorted, so a column in two tables lists them in a fixed order
        "WHERE table_schema = 'analytics' AND column_name = ?", [column]).fetchall()   # the marts only: where the model should have looked
    where[tables] += 1
    print(f"{q.question_id}: no column {column}; it is in {tables}")
print(f"schema-only queries that don't run: {where.total()}")
for tables, n in where.items():
    print(f"missing column only {tables} has: {n}")
