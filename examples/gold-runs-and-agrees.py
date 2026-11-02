"""Check the gold before trusting it: every golden SQL runs and returns rows, and each check query agrees with it."""
import duckdb
from lib.golden import golden_result, load_golden, results_match
from lib.warehouse import connect

con = connect()
answerable = [q for q in load_golden() if q.kind == "answer"]
results, failed = {}, []
for q in answerable:
    try:
        results[q.question_id] = golden_result(con, q)
    except duckdb.Error:
        failed.append(q.question_id)
empty = [qid for qid, rows in results.items() if not rows or any(v is None for row in rows for v in row)]
print(f"golden SQL that runs: {len(results)} of {len(answerable)}")
print(f"golden SQL that fails: {', '.join(failed) or 'none'}")
print(f"empty or NULL results: {len(empty)}")

checked = [q for q in answerable if q.check_sql and q.question_id in results]
agree = [q for q in checked if results_match(con.execute(q.check_sql).fetchall(), results[q.question_id],
                                             q.order_matters, q.tolerance, q.absolute)]
print(f"questions with a check query: {len(checked)}")
print(f"checks that agree: {len(agree)} of {len(checked)}")

# One question, two readings: "top country for refunds" by number of refunds, and by refund rate (gq-028's definition).
by_count, by_rate = con.execute("""
    SELECT arg_max(country, refunds), arg_max(country, refunded / gross) FROM (
        SELECT o.country, count(r.refund_id) AS refunds, sum(r.amount_eur) AS refunded,
               sum(o.gross_revenue_eur) AS gross
        FROM analytics.fct_orders AS o
        JOIN analytics.dim_date AS d ON d.date_day = o.order_date_local
        LEFT JOIN analytics.fct_refunds AS r USING (order_id)
        WHERE o.status <> 'cancelled' AND d.fiscal_year = 2026
        GROUP BY o.country)""").fetchall()[0]
print(f"top country by number of refunds: {by_count}")
print(f"top country by refund rate: {by_rate}")
print(f"gq-028 golden: {results['gq-028'][0][0]}")

