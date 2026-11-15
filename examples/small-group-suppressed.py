"""Marketing's answer to the June breakdown by channel and country, with every group behind fewer than the minimum held back.
The customer counts behind Singapore's web and app orders show why its app group is suppressed."""
from lib.policies import PolicyLayer, policy_for
from lib.semantic import MetricRequest, load
from lib.warehouse import connect

con, layer = connect(), load()
marketing = PolicyLayer(layer, policy_for("marketing"), con)
print(f"minimum group size: {marketing.policy.minimum_group_size}")
print(f"metrics marketing can't be given: {', '.join(sorted(marketing.denied_metrics))}")

request = MetricRequest(("net_revenue", "orders"), ("order__channel", "order__country"),
                        {"order__region": "APAC", "metric_time__month": "2026-06"})
answer = marketing.query(con, request)
print(answer.show())
print(f"groups: {len(answer.rows)}")
print(f"groups suppressed: {marketing.suppressed}")
counts = marketing.people_counts(con, request)
print(f"customers behind app in SG: {counts['app', 'SG']}")     # keys follow the group-by: channel, then country
print(f"customers behind web in SG: {counts['web', 'SG']}")
