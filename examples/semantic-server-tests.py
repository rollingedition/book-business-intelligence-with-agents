"""In-memory tests of the semantic server, one role per server, and one check that a test can fail."""
import anyio

from lib.golden import golden_result, load_golden, results_match
from lib.semantic import load
from lib.semantic_server import build_server, call, run_tests
from lib.warehouse import connect

con, layer = connect(), load()
server = lambda role, region=None: build_server(role, region, con, layer)      # each on the role's own database
gold = golden_result(con, next(q for q in load_golden() if q.question_id == "gq-017"))
lead_request = {"metrics": ["net_revenue"], "group_by": ["order__country"], "filters": {"metric_time__year": 2025}}
HIDDEN_FROM_SUPPORT = {"average_order_value", "gross_revenue", "line_net_revenue", "net_revenue", "refund_rate"}


async def test_lead_answer_matches_the_golden_result():
    result = await call(server("regional_lead", "EMEA"), "query_metric", lead_request)
    assert results_match(result.structured_content["answer"]["rows"], gold)


async def test_lead_cannot_ask_for_another_region():
    result = await call(server("regional_lead", "EMEA"), "query_metric", {"metrics": ["orders"],
                        "filters": {"order__region": "APAC"}})
    assert not result.is_error and result.structured_content["answer"]["reason"].startswith("forbidden")


async def test_lead_database_holds_no_other_region():        # the policy layer bypassed: SQL straight to the database
    regions = server("regional_lead", "EMEA").database.execute("SELECT DISTINCT region FROM analytics.fct_orders")
    assert regions.fetchall() == [("EMEA",)]


async def test_support_catalog_hides_every_revenue_metric():
    listed = (await call(server("support"), "list_metrics", {})).structured_content["text"]
    assert HIDDEN_FROM_SUPPORT == set(layer.metrics) - {line[2:].split(":")[0] for line in listed.splitlines()}


async def test_marketing_small_groups_are_suppressed():
    result = await call(server("marketing"), "query_metric", {"metrics": ["orders"], "group_by":
                        ["order__channel", "order__country"], "filters": {"metric_time__month": "2026-06"}})
    assert any("(under 10)" in row for row in result.structured_content["answer"]["rows"])


async def test_unknown_dimension_is_a_tool_error_with_a_hint():
    result = await call(server("finance"), "query_metric", {"metrics": ["orders"], "group_by": ["order_region"]})
    assert result.is_error and "did you mean order__region?" in result.content[0].text


async def main():
    passed = await run_tests(globals())
    print(f"tests passed: {passed} of {passed}")
    unbound = (await call(server("analyst"), "query_metric", lead_request)).structured_content["answer"]["rows"]
    print(f"the lead's request on an analyst's server differs from the lead's gold: {not results_match(unbound, gold)}")


anyio.run(main)
