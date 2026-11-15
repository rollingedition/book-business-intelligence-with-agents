"""What the schema tells a model about revenue, and three March 2026 totals that all fit it. The three printed totals
carry the paragraph's point: they differ, and only the one that leaves out cancelled orders follows the finance definition."""
from lib.context import build_context
from lib.warehouse import connect

con = connect()
schema = build_context(con, "", layers=("schema",))      # no question, so only the schema layer is built
print(f"tables in the schema: {schema.text.count('CREATE TABLE')}")
print(f"schema tokens (estimated): {schema.tokens}")
for line in schema.text.splitlines():
    if "analytics.fct_orders " in line or "analytics.orders_legacy " in line:
        print(line)

march = "BETWEEN DATE '2026-03-01' AND DATE '2026-03-31'"   # the window of the question, on the business day
candidates = {
    "orders_legacy.revenue": f"SELECT sum(revenue) FROM analytics.orders_legacy WHERE order_date {march}",
    "fct_orders.net_revenue_eur, every order":
        f"SELECT sum(net_revenue_eur) FROM analytics.fct_orders WHERE order_date_local {march}",
    "fct_orders.net_revenue_eur, not cancelled":
        f"SELECT sum(net_revenue_eur) FROM analytics.fct_orders WHERE order_date_local {march} "
        "AND status <> 'cancelled'",          # net revenue leaves out cancelled orders, as the status note says
}
for name, sql in candidates.items():
    (total,), = con.execute(sql).fetchall()
    print(f"{name}: {total:,.2f}")
