"""Two queries written differently for the same golden question: compare their text, then compare their results.
The point rests on the last two result lines, "results match": the order-lines query matches the golden result, and
the query that forgets cancelled orders does not. The asserts at the end check both."""
import sqlglot
from lib.golden import golden_result, load_golden, results_match
from lib.warehouse import connect

con = connect()
q = next(q for q in load_golden() if q.question_id == "gq-001")   # net revenue in fiscal year 2026
by_orders, by_lines = q.golden_sql, q.check_sql                    # orders joined to dim_date; lines by date range
forgets_cancelled = by_orders.replace("o.status <> 'cancelled' AND ", "")  # the golden SQL's cancelled-order filter, removed


def normalized(sql: str) -> str:
    # parses and writes the SQL back in DuckDB's form, so spacing and identifier case don't count as differences
    return sqlglot.parse_one(sql, read="duckdb").sql(dialect="duckdb", normalize=True, pretty=False)


golden = golden_result(con, q)
for name, sql in [("by lines", by_lines), ("forgets cancelled", forgets_cancelled)]:
    rows = con.execute(sql).fetchall()
    print(f"{name}: {rows[0][0]:,.2f} against golden {golden[0][0]:,.2f}")
    print(f"{name} same text: {sql == by_orders}")
    print(f"{name} same normalized text: {normalized(sql) == normalized(by_orders)}")
    print(f"{name} results match: {results_match(rows, golden)}")
# a change to either result must fail this run, as the prose states both facts
assert results_match(con.execute(by_lines).fetchall(), golden)
assert not results_match(con.execute(forgets_cancelled).fetchall(), golden)
