"""The golden questions whose right answer is a decline: which are ambiguous, which are unanswerable, and why."""
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
            found = con.execute("""SELECT string_agg(table_name || '.' || column_name, ', ') FROM information_schema.columns
                                   WHERE table_schema IN ('raw', 'analytics') AND regexp_matches(column_name, ?)""",
                                [words]).fetchall()[0][0]
            print(f"  columns matching {words!r}: {found or 'none'}")

cost = con.execute("""SELECT string_agg(table_name || '.' || column_name, ', ') FROM information_schema.columns
                      WHERE table_schema IN ('raw', 'analytics') AND regexp_matches(column_name, 'cost')""").fetchall()
print(f"columns named for cost: {cost[0][0] or 'none'}")
reasons = [r for (r,) in con.execute("SELECT DISTINCT reason FROM analytics.fct_refunds ORDER BY 1").fetchall()]
print(f"refund reasons: {', '.join(reasons)}")
print(f"last order day: {con.execute('SELECT max(order_date_local) FROM analytics.fct_orders').fetchall()[0][0]}")

# "Which region is doing best?" in fiscal 2026, by three metrics the layer defines.
fiscal_2026 = {"metric_time__fiscal_year": 2026}
for metric, order in (("net_revenue", "-net_revenue"), ("orders", "-orders"), ("refund_rate", "refund_rate")):
    answer = layer.query(con, MetricRequest((metric,), ("order__region",), fiscal_2026, (order,), 1))
    print(f"best region by {order.lstrip('-')}{' (lowest)' if order == metric else ''}: {answer.rows[0][0]}")

# "What was revenue in Q2?" read as a calendar quarter and as a fiscal quarter of the same year.
for name, value in (("metric_time__quarter", "2025-04-01"), ("metric_time__fiscal_quarter", "2026-Q2")):
    (revenue,), = layer.query(con, MetricRequest(("net_revenue",), (), {name: value})).rows
    print(f"net revenue, {name.removeprefix('metric_time__')} {value}: {revenue:,.2f}")
