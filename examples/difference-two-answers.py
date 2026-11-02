"""Two answers marketing may see, each with no small group, subtracted to recover a group the policy suppressed."""
from decimal import Decimal

from lib.policies import PolicyLayer, policy_for
from lib.semantic import MetricRequest, load
from lib.warehouse import connect

con, layer = connect(), load()
marketing = PolicyLayer(layer, policy_for("marketing"), con)
june_apac = {"order__region": "APAC", "metric_time__month": "2026-06"}

by_channel = marketing.query(con, MetricRequest(("net_revenue",), ("order__channel",), june_apac))
print(by_channel.show())
print(f"first answer, groups suppressed: {marketing.suppressed}")
whole = MetricRequest(("net_revenue",), (), june_apac)
total = marketing.query(con, whole)
print(f"second answer, APAC's total: {total.rows[0][0]:,.2f}")
print(f"second answer, groups suppressed: {marketing.suppressed}")
print(f"second answer, customers behind it: {marketing.people_counts(con, whole)[()]}")

shown = sum(value for _, value in by_channel.rows if isinstance(value, Decimal))
print(f"total minus the channels shown: {total.rows[0][0] - shown:,.2f}")
actual = dict(layer.query(con, MetricRequest(("net_revenue",), ("order__channel",), june_apac)).rows)
print(f"the suppressed group's value, as the analyst sees it: {actual['(none)']:,.2f}")
print(f"customers behind it: {marketing.people_counts(con, MetricRequest(('net_revenue',), ('order__channel',), june_apac))[('(none)',)]}")
