"""The golden questions whose right answer is a decline: which are ambiguous, which are unanswerable, and why.
The point that unanswerable questions have nothing to compute from rests on the "columns matching" lines, and the point
that ambiguous ones have too many answers rests on the "best region" and "net revenue" lines."""
from lib.golden import load_golden
from lib.semantic import MetricRequest, load
from lib.warehouse import connect

con, layer = connect(), load()
# Each decline question's category: PRACTIQ's names, and TrustSQL's for the forecast. Words to look for in the schema.
CATEGORIES = {"gq-005": ("beyond SQL: a forecast", "forecast|predict"), "gq-019": ("ambiguous SELECT column", None),
              "gq-020": ("ambiguous SELECT column", None), "gq-021": ("nonexistent SELECT column", "ship"),
              "gq-042": ("ambiguous filter criteria", None), "gq-043": ("ambiguous values within a column", None),
              "gq-044": ("unsupported join", "view|page"), "gq-045": ("nonexistent WHERE column", "deliver|promise")}
for q in load_golden():
    if q.kind == "decline":
        category, words = CATEGORIES[q.question_id]
        print(f"{q.question_id} ({q.split}, {q.decline_type}): {category}")
        if words:
            # raw and analytics are the only schemas with data; the layer reads from both
            found = con.execute("""SELECT string_agg(table_name || '.' || column_name, ', ') FROM information_schema.columns
                                   WHERE table_schema IN ('raw', 'analytics') AND regexp_matches(column_name, ?)""",
                                [words]).fetchall()[0][0]
            print(f"  columns matching {words!r}: {found or 'none'}")

# the match is on the name: a column named for cost is the product's unit cost, which is not the shipping the question asks for
cost = con.execute("""SELECT string_agg(table_name || '.' || column_name, ', ') FROM information_schema.columns
                      WHERE table_schema IN ('raw', 'analytics') AND regexp_matches(column_name, 'cost')""").fetchall()
print(f"columns named for cost: {cost[0][0] or 'none'}")
reasons = [r for (r,) in con.execute("SELECT DISTINCT reason FROM analytics.fct_refunds ORDER BY 1").fetchall()]
print(f"refund reasons: {', '.join(reasons)}")
print(f"last order day: {con.execute('SELECT max(order_date_local) FROM analytics.fct_orders').fetchall()[0][0]}")

# "Which region is doing best?" in fiscal 2026, by three metrics the layer defines.
fiscal_2026 = {"metric_time__fiscal_year": 2026}
for metric, order in (("net_revenue", "-net_revenue"), ("orders", "-orders"), ("refund_rate", "refund_rate")):
    # a leading minus sorts descending, so net revenue and orders put the largest first; refund_rate sorts ascending,
    # so its first row is the lowest rate; the limit of 1 keeps that one row
    answer = layer.query(con, MetricRequest((metric,), ("order__region",), fiscal_2026, (order,), 1))
    print(f"best region by {order.lstrip('-')}{' (lowest)' if order == metric else ''}: {answer.rows[0][0]}")

# Q2 read as a calendar quarter and as a fiscal quarter: calendar Q2 starts on April 1, fiscal Q2 2026 runs May to July.
for name, value in (("metric_time__quarter", "2025-04-01"), ("metric_time__fiscal_quarter", "2026-Q2")):
    # one row with one column, so the unpacking gives the revenue total for the period
    (revenue,), = layer.query(con, MetricRequest(("net_revenue",), (), {name: value})).rows
    print(f"net revenue, {name.removeprefix('metric_time__')} {value}: {revenue:,.2f}")
