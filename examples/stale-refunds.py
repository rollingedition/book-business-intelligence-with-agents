"""Check freshness: refunds stopped loading after June 26, 2026, and come weeks after the order."""
from datetime import date

from lib.declining import (FEEDS, SETTLING_DAYS, DecliningToolbox, check_freshness, refund_delays, refund_shortfall,
                           settled_refund_rate)
from lib.semantic import MetricRequest, load
from lib.warehouse import connect, data_as_of

con, layer = connect(), load()
catalog = [c for (c, t, *_) in con.execute("DESCRIBE SELECT * FROM duckdb_tables()").fetchall() if "TIME" in t]
print(f"duckdb_tables() time columns: {', '.join(catalog) or 'none'}")
for table in ("analytics.fct_orders", "analytics.fct_refunds", "analytics.dim_customers"):
    print(f"data as of, {table}: {data_as_of(con, table)}")
delays = refund_delays(con)                # the longest delay on settled orders is what SETTLING_DAYS uses
print(f"refunds per day: {delays['per day']:.1f}\nmedian days from order to refund: {delays['median']}\n"
      f"refunds within 30 days of the order: {delays['within 30']:.0%}\n"
      f"refunds within 45 days of the order: {delays['within 45']:.0%}\n"
      f"longest days from order to refund: {delays['longest']}\n"
      f"settling window, order_refunds: {SETTLING_DAYS['order_refunds']} days")
for month in ("2026-04", "2026-05", "2026-06"):           # without a check, the layer answers for any month
    (rate,), = layer.query(con, MetricRequest(("refund_rate",), (), {"metric_time__month": month})).rows
    print(f"refund rate, {month}, unchecked: {rate:.2%}")
# Why May and June are short, estimated from the twelve months whose refunds have all come.
print(f"refund rate, settled months: {settled_refund_rate(con):.2%}")
for month, end in (("2026-05", date(2026, 6, 1)), ("2026-06", date(2026, 7, 1))):
    short = refund_shortfall(con, end)
    print(f"{month}, settled months' rate with refunds as loaded: {short['as loaded']:.2%}\n"
          f"{month}, points short, refunds not loaded: {short['not loaded'] * 100:.2f}\n"
          f"{month}, points short, refunds not happened yet: {short['not happened'] * 100:.2f}\n"
          f"{month}, share of the shortfall not loaded: {short['share not loaded']:.0%}")

print(f"new customers, feed for dim_customers: {FEEDS['analytics.dim_customers']}")  # customers load at sign-up
for name, metric in (("refund rate", "refund_rate"), ("new customers", "new_customers")):
    for check in check_freshness(con, layer, MetricRequest((metric,), (), {"metric_time__month": "2026-06"})):
        print(f"{name}, 2026-06: {check.describe()}")
for month in ("2026-06", "2026-05", "2026-04"):
    query = {"metrics": ["refund_rate"], "filters": {"metric_time__month": month}}
    a = (r := DecliningToolbox(con, layer).call("query_metric", query)).answer
    print(f"refund rate, {month}, checked: "
          + (f"{a.rows[0][0]:.2%}, data as of {a.provenance.data_as_of}" if a.answered else r.content))
