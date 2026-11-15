"""Change the golden result for net revenue by region in March 2026 in the ways real answers differ, and compare.
Then move a ratio gold, gq-033's conversion rates, by a near miss. The prose's claims about thousands and about the
near miss rest on the lines that print True or False, and the asserts check them."""
from lib.golden import golden_result, load_golden, results_match
from lib.warehouse import connect

con = connect()
q = next(q for q in load_golden() if q.question_id == "gq-002")
golden = sorted((region, float(revenue)) for region, revenue in golden_result(con, q))  # sorted by region, so the variants line up
print(f"golden: {golden}")
print(f"tolerance: {q.tolerance:.2%} relative")
print(f"absolute slack: {q.absolute}")

variants = {
    "rows reversed": golden[::-1],
    "columns swapped": [(revenue, region) for region, revenue in golden],
    "extra month column": [(region, "2026-03", revenue) for region, revenue in golden],
    "rounded to whole euros": [(region, round(revenue)) for region, revenue in golden],
    "rounded to thousands": [(region, round(revenue, -3)) for region, revenue in golden],  # round(x, -3) rounds to the nearest thousand
    "in thousands of euros": [(region, revenue / 1000) for region, revenue in golden],  # same numbers, unit changed to thousands
    "one region missing": golden[:-1],  # drops the last region
}
for name, rows in variants.items():
    print(f"{name}: {results_match(rows, golden, q.order_matters, q.tolerance)}")
# reporting in thousands of euros must fail: a change of unit the agent doesn't state is a real error
assert not results_match(variants["in thousands of euros"], golden, q.order_matters, q.tolerance)

ranked = sorted(golden, key=lambda row: -row[1])  # highest revenue first, so the reversed list is the wrong order
print(f"ranking reversed, order matters: {results_match(ranked[::-1], ranked, order_matters=True)}")

# A ratio: gq-033's conversion rates, rounded to four places, with its absolute slack of half that last place.
rates_q = next(q for q in load_golden() if q.question_id == "gq-033")
rates = [(channel, float(rate)) for channel, rate in golden_result(con, rates_q)]
near_miss = [(channel, rate + 0.004) for channel, rate in rates]  # 0.004 is about 3% of each rate
print(f"gq-033 rates: {min(r for _, r in rates):.4f} to {max(r for _, r in rates):.4f}")
print(f"gq-033 absolute slack: {rates_q.absolute:.5f}")
print(f"rates 0.004 higher, gq-033's rule: "
      f"{results_match(near_miss, rates, rates_q.order_matters, rates_q.tolerance, rates_q.absolute)}")
print(f"rates 0.004 higher, half a cent of slack: {results_match(near_miss, rates, rates_q.order_matters, rates_q.tolerance)}")
# under the question's own slack the near miss is a miss; with half a cent of slack the same near miss matches
assert not results_match(near_miss, rates, rates_q.order_matters, rates_q.tolerance, rates_q.absolute)
assert results_match(near_miss, rates, rates_q.order_matters, rates_q.tolerance)
