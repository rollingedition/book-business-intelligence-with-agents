"""Compile the same requests with MetricFlow and with the book's compiler, run both, and compare the results."""
from lib.golden import results_match
from lib.metricflow_bridge import as_dates, engine, explain_sql
from lib.semantic import MetricRequest as Request, load
from lib.warehouse import connect

con = connect()
layer, mf = load(), engine(con)   # both read examples/data/semantic/*.yml
requests = [
    Request(("net_revenue",), ("order__region",), {"metric_time__month": "2026-03"}),
    Request(("net_revenue", "orders"), ("metric_time__fiscal_quarter",), {"metric_time__fiscal_year": 2026}),
    Request(("line_net_revenue", "units_sold"), ("product__category",), {"metric_time__year": 2025}),
    Request(("units_sold",), ("order__customer__region",), {"metric_time__year": 2025}),
    Request(("refund_rate",), ("order__country",), {"metric_time__fiscal_year": 2026}),
    Request(("average_order_value",), ("order__channel",), {"metric_time__month": "2026-03"}),
    Request(("refunds", "order_refunds"), ("metric_time__month",), {"metric_time__year": 2025}),
    Request(("new_customers",), ("customer__region",), {"metric_time__year": 2025}),
]


agree = 0
for request in requests:
    ours = con.execute(layer.sql(request)).fetchall()
    theirs = as_dates(con.execute(explain_sql(mf, request)).fetchall())
    same = results_match(ours, theirs, tolerance=1e-9)
    agree += same
    print(f"{', '.join(request.metrics)} by {', '.join(request.group_by)}: {len(ours)} rows, agree: {same}")
month = requests[6]
print(f"MetricFlow's type for metric_time__month: {type(con.execute(explain_sql(mf, month)).fetchone()[0]).__name__}")
print(f"the book's type for metric_time__month: {type(con.execute(layer.sql(month)).fetchone()[0]).__name__}")
print(f"requests compared: {len(requests)}")
print(f"requests that agree: {agree}")

print(explain_sql(mf, requests[0]))
try:
    explain_sql(mf, Request(("net_revenue",), ("product__category",), {"metric_time__year": 2025}))
except Exception as e:
    print(f"MetricFlow on net_revenue by product__category: {type(e).__name__}")
    lines = [line.strip() for line in str(e).splitlines()]
    cause = lines.index("* No valid join paths exist from the measure to the group-by-item.")
    print(f"one cause MetricFlow lists: {lines[cause][2:]} {lines[cause + 1]}")

