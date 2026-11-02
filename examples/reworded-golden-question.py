"""Read a wrong answer: gq-031 once asked about "items", which allows units or order lines. It now asks for units."""
from dataclasses import replace

from lib.golden import golden_result, load_golden, schema_only_outcome
from lib.model import RecordedModel
from lib.prompts import schema_only_messages
from lib.tools import extract_sql
from lib.warehouse import connect, describe_schema

con = connect()
schema, model = describe_schema(con), RecordedModel("schema-only-sql")
q = next(q for q in load_golden() if q.question_id == "gq-031")
print(f"gq-031 golden: {golden_result(con, q)[0][0]}")
for wording, asked in [("items", replace(q, question="How many items did an order contain on average in 2025?")),
                       ("units", q)]:
    sql = extract_sql(model.complete(schema_only_messages(schema, asked.question)))
    print(f"{wording} wording: {asked.question}")
    print(f"baseline answer, {wording} wording: {con.execute(sql).fetchall()[0][0]:.4f}")
    print(f"baseline outcome, {wording} wording: {schema_only_outcome(con, model, schema, asked)}")
