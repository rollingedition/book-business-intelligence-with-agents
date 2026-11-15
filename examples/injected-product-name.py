"""A product name carrying an instruction, read by the model that writes the answer in words, and checked by code before anything is shown.
Each name's check lines show which summaries the code rejects, and the shown-after-the-check line gives the count that reaches the reader."""
import tomllib
from pathlib import Path

from lib.model import RecordedModel
from lib.policies import PolicyLayer, policy_for
from lib.semantic import MetricRequest, load
from lib.untrusted import missing_numbers, summary_messages, unsupported_numbers, warehouse_with_product_name
from lib.warehouse import connect

probes = tomllib.loads(Path("data/shop/access_probes.toml").read_text())["untrusted"]
layer, model = load(), RecordedModel("injected-values")
role = "finance"                 # a role whose policy allows units_sold; marketing's refuses it
top_five = MetricRequest(("units_sold",), ("product__product_name",), {"metric_time__month": "2026-06"},
                         ("-units_sold",), 5)     # the five best sellers: largest units first, five rows
# None is the warehouse as shipped, with the product's real name
names = [("original", None)] + [(n["name_id"], n["name"]) for n in probes["product_names"]]
shown, ran, units = 0, set(), set()
for name_id, name in names:
    con = connect() if name is None else warehouse_with_product_name(probes["product"], name)
    # The query runs under the role's policy before the model reads a single value.
    answer = PolicyLayer(layer, policy_for(role), con).query(con, top_five)
    ran.add(answer.provenance.sql)
    units.add(tuple(row[1] for row in answer.rows))     # row[0] is the product name, row[1] its units
    if name:
        print(f"{name_id}, the product's name: {name}")
    print(f"{name_id}, read as {answer.provenance.role}, units: {', '.join(str(row[1]) for row in answer.rows)}")
    for prompt in ("plain", "delimited"):
        # the delimited prompt puts the result in tags and says the tagged text is data
        summary = model.complete(summary_messages(probes["question"], answer, delimited=prompt == "delimited"))
        # the question's own numbers, such as a year asked, may appear in a summary without being in the result
        extra, missing = unsupported_numbers(summary, answer, (probes["question"],)), missing_numbers(summary, answer)
        shown += not extra and not missing
        print(f"{name_id}, {prompt}: {summary.strip()}")
        print(f"{name_id}, {prompt}, check: numbers not in the result {extra or 'none'}; "
              f"numbers left out {missing or 'none'}")
# the policy fixes one SQL text and one set of units, whatever the product name says
print(f"same SQL and same units under every name: {'yes' if len(ran) == len(units) == 1 else 'no'}")
print(f"summaries: {len(names) * 2}")     # two prompts for each name
print(f"shown after the check: {shown}")
