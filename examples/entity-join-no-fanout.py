"""Ask for net revenue by product category: the layer refuses the fan-out join and points to a line-level metric."""
from lib.semantic import FanOutError, MetricRequest, load
from lib.warehouse import connect

layer, con = load(), connect()
in_2025 = {"metric_time__year": 2025}

try:
    layer.sql(MetricRequest(("net_revenue",), ("product__category",), in_2025))
except FanOutError as e:
    print(f"refused: {e}")

# What a hand-written join does with the same question: each order's revenue repeats once per line.
(joined,), = con.execute("""
    SELECT sum(o.net_revenue_eur) FROM analytics.fct_orders AS o
    JOIN analytics.fct_order_lines AS l USING (order_id)
    WHERE o.status <> 'cancelled' AND year(o.order_date_local) = 2025""").fetchall()
(total,), = layer.query(con, MetricRequest(("net_revenue",), filters=in_2025)).rows
print(f"net revenue, 2025: {total:,.2f}")
print(f"summed over the joined lines: {joined:,.2f}")
print(f"inflated by: {joined / total - 1:.0%}")

request = MetricRequest(("line_net_revenue",), ("product__category",), in_2025, order_by=("-line_net_revenue",))
print(layer.sql(request))
answer = layer.query(con, request)
print(answer.show())
by_category = sum(row[1] for row in answer.rows)
print(f"categories add up to: {by_category:,.2f}")
print(f"difference from net revenue: {abs(by_category - total):,.2f}")
