"""An access rule in the prompt, against the same requests run under the regional lead's policy."""
import tomllib
from pathlib import Path

from lib.agent import run_agent
from lib.metric_tools import MetricToolbox, catalog
from lib.model import RecordedModel
from lib.policies import PolicyError, PolicyLayer, policy_for
from lib.prompts import region_rule_prompt
from lib.semantic import MetricRequest, load
from lib.warehouse import connect

probes = tomllib.loads(Path("data/shop/access_probes.toml").read_text())
con, layer, region = connect(), load(), probes["region"]
system = region_rule_prompt(catalog(layer), region)          # the rule is a sentence in the prompt
apac = PolicyLayer(layer, policy_for("regional_lead", region), con)
leaked = refused = 0
requests = {}
for probe in probes["region_probes"]:
    trace = run_agent(probe["question"], system, RecordedModel("prompt-rule-runs"),
                      MetricToolbox(con, layer, role="regional_lead"), max_steps=4)
    request = requests[probe["probe_id"]] = MetricRequest.from_arguments(trace.steps[-2].arguments)
    try:
        allowed = apac.query(con, request).rows
    except PolicyError:
        allowed, refused = None, refused + 1
    outside = trace.answer.answered and trace.answer.rows != allowed
    leaked += outside
    print(f"{probe['probe_id']} ({probe['asks']}): prompt rule {'answered' if trace.answer.answered else 'declined'}"
          f"{', with data outside ' + region if outside else ''}; policy "
          f"{'refused' if allowed is None else 'returned ' + region + ' rows only'}")
print(f"probes: {len(probes['region_probes'])}")
print(f"answered with data outside {region} under the prompt rule: {leaked}")
print(f"refused under the policy: {refused}")
whole_shop = apac.query(con, requests["rp-5"])
print(f"rp-5 under the policy, provenance filters: {whole_shop.provenance.filters}")
