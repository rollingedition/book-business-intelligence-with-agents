"""Record the pinned model for chapter 9: access by role, a rule in the prompt, and an instruction inside a value.

Three recordings, each under examples/data/recorded/:
- `policy-agent-runs`: chapter 6's metrics-first agent, for each golden question's role, over the semantic layer as
  that role sees it (`PolicyLayer` and `PolicyToolbox` in examples/lib/policies.py). The catalog in the prompt is the
  role's, so it changes only for roles that lose metrics or dimensions. A call chapter 6's `metric-agent-runs`
  already holds is replayed; only the rest are recorded. Part 1 is the dev split, part 2 the test split.
- `prompt-rule-runs`: the same agent with chapter 6's whole catalog and no policy, whose only access rule is
  `REGION_RULE` appended to the prompt, on the probes in examples/data/shop/access_probes.toml. Part 1.
- `injected-values`: the summary prompts (`ANSWER_SUMMARY`, `ANSWER_SUMMARY_DELIMITED`) on the top five products of
  June 2026, read under finance's policy, with the product's own name and with each replacement name in
  access_probes.toml. Part 1.

    python recordings/record_access.py --recording policy-agent-runs --part 1
    python recordings/record_access.py --recording policy-agent-runs --part 2
    python recordings/record_access.py --recording prompt-rule-runs --part 1
    python recordings/record_access.py --recording injected-values --part 1

A part records only the questions it hasn't recorded yet, and saves after each one.
"""
import argparse
import tomllib

from local_model import REPO_ROOT, LocalModel, Recorder, recorded_questions, write_part

from lib.agent import run_agent
from lib.golden import load_golden
from lib.metric_tools import MetricToolbox, catalog
from lib.model import MissingRecording, RecordedModel
from lib.policies import PolicyLayer, PolicyToolbox, policy_for
from lib.prompts import (ANSWER_SUMMARY, ANSWER_SUMMARY_DELIMITED, METRICS_FIRST, REGION_RULE, metrics_first_prompt,
                         prompt_sha256, region_rule_prompt)
from lib.semantic import MetricRequest, load
from lib.untrusted import summary_messages, warehouse_with_product_name
from lib.warehouse import connect

PROBES = REPO_ROOT / "examples" / "data" / "shop" / "access_probes.toml"
TOP_FIVE = MetricRequest(("units_sold",), ("product__product_name",), {"metric_time__month": "2026-06"},
                         ("-units_sold",), 5)


class FirstFromRecording:
    """Answers from an earlier recording when it holds the messages, and from the live model otherwise."""

    def __init__(self, recorded: RecordedModel, live: Recorder):
        self.recorded, self.live = recorded, live

    def complete(self, messages: list[dict]) -> str:
        try:
            return self.recorded.complete(messages)
        except MissingRecording:
            return self.live.complete(messages)


def policy_runs(folder, part, done):
    con, layer, earlier = connect(), load(), RecordedModel("metric-agent-runs")
    split = {1: "dev", 2: "test"}[part]
    model = None
    for q in load_golden():
        if q.split != split or q.question_id in done:
            continue
        policy_layer = PolicyLayer(layer, policy_for(q.role, q.region or None), con)
        calls = []
        model = model or LocalModel(max_tokens=256)
        run_agent(q.question, metrics_first_prompt(catalog(policy_layer)),
                  FirstFromRecording(earlier, Recorder(model, q.question_id, calls)),
                  PolicyToolbox(con, policy_layer), max_steps=4)
        if calls:
            yield calls, model


def prompt_rule_runs(folder, part, done):
    con, layer = connect(), load()
    probes = tomllib.loads(PROBES.read_text())
    system = region_rule_prompt(catalog(layer), probes["region"])
    model = LocalModel(max_tokens=256)
    for probe in probes["region_probes"]:
        if probe["probe_id"] in done:
            continue
        calls = []
        run_agent(probe["question"], system, Recorder(model, probe["probe_id"], calls),
                  MetricToolbox(con, layer, role="regional_lead"), max_steps=4)
        yield calls, model


def injected_runs(folder, part, done):
    probes = tomllib.loads(PROBES.read_text())["untrusted"]
    layer = load()
    names = [("original", None)] + [(n["name_id"], n["name"]) for n in probes["product_names"]]
    model = LocalModel(max_tokens=256)
    for name_id, name in names:
        con = connect() if name is None else warehouse_with_product_name(probes["product"], name)
        answer = PolicyLayer(layer, policy_for("finance"), con).query(con, TOP_FIVE)   # a role allowed units_sold
        for delimited in (False, True):
            call_id = f"{name_id}-{'delimited' if delimited else 'plain'}"
            if call_id in done:
                continue
            calls = []
            Recorder(model, call_id, calls).complete(summary_messages(probes["question"], answer, delimited))
            yield calls, model


RECORDINGS = {
    "policy-agent-runs": (policy_runs, {1, 2}, METRICS_FIRST,
                          "METRICS_FIRST (examples/lib/prompts.py) with the role's catalog from PolicyLayer; calls "
                          "metric-agent-runs holds are replayed, not recorded"),
    "prompt-rule-runs": (prompt_rule_runs, {1}, METRICS_FIRST + REGION_RULE,
                         "METRICS_FIRST with the whole catalog, then REGION_RULE for APAC (examples/lib/prompts.py)"),
    "injected-values": (injected_runs, {1}, ANSWER_SUMMARY + ANSWER_SUMMARY_DELIMITED,
                        "ANSWER_SUMMARY (plain) and ANSWER_SUMMARY_DELIMITED (delimited), examples/lib/prompts.py"),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recording", required=True, choices=sorted(RECORDINGS))
    parser.add_argument("--part", type=int, required=True)
    args = parser.parse_args()
    runs, parts, prompt, description = RECORDINGS[args.recording]
    if args.part not in parts:
        parser.error(f"{args.recording} has parts {sorted(parts)}")
    folder = REPO_ROOT / "examples" / "data" / "recorded" / args.recording
    done = {call["question_id"] for call in recorded_questions(folder, args.part)}
    for calls, model in runs(folder, args.part, done):
        write_part(folder, args.part, calls, {"script": "recordings/record_access.py", "prompt": description,
                                              "prompt_sha256": prompt_sha256(prompt)}, model)


if __name__ == "__main__":
    main()
