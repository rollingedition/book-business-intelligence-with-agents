"""A ratio metric divides two separately aggregated sums; averaging per-order ratios gives a different number."""
from lib.golden import golden_result, load_golden, results_match
from lib.semantic import MetricRequest, load
from lib.warehouse import connect

layer, con = load(), connect()
fiscal_2026 = {"metric_time__fiscal_year": 2026}

request = MetricRequest(("refund_rate",), ("order__region",), fiscal_2026)
print(layer.sql(request))
for region, rate in layer.query(con, request).rows:
    print(f"refund rate, {region}: {rate:.2%}")

# The tempting shortcut: each order's refunds over its gross revenue, averaged per region.
for region, rate in con.execute("""
    SELECT o.region, avg(coalesce(r.refunded, 0) / o.gross_revenue_eur)
    FROM analytics.fct_orders AS o
    JOIN analytics.dim_date AS d ON d.date_day = o.order_date_local
    LEFT JOIN (SELECT order_id, sum(amount_eur) AS refunded FROM analytics.fct_refunds GROUP BY order_id) AS r
        USING (order_id)
    WHERE o.status <> 'cancelled' AND d.fiscal_year = 2026
    GROUP BY o.region ORDER BY o.region""").fetchall():
    print(f"average of per-order rates, {region}: {rate:.2%}")

golden = {q.question_id: q for q in load_golden()}
top = layer.query(con, MetricRequest(("refund_rate",), ("order__country",), fiscal_2026, ("-refund_rate",), 1))
print(f"highest refund rate: {top.rows[0][0]}")
print(f"gq-028 matches golden: {results_match([top.rows[0][:1]], golden_result(con, golden['gq-028']))}")

average = layer.query(con, MetricRequest(("average_order_value",), ("order__region",), {"metric_time__month": "2026-03"}))
print(average.show())
print(f"gq-009 matches golden: {results_match(average.rows, golden_result(con, golden['gq-009']))}")
