"""The book's agent as an MCP host on every golden question, each tool on the asker's server, against chapter 9."""
from collections import Counter

import anyio

from lib.agent import run_agent
from lib.golden import golden_result, grade, load_golden
from lib.metric_tools import catalog
from lib.model import RecordedModels
from lib.policies import PolicyLayer, PolicyToolbox, policy_for
from lib.prompts import metrics_first_prompt
from lib.semantic import load
from lib.semantic_server import ask_through_server, build_server
from lib.warehouse import connect

con, layer = connect(), load()
model = RecordedModels("metric-agent-runs", "policy-agent-runs", "mcp-host-runs")   # ch 11 recorded the rest


async def main():
    counts, changed, details, errors = Counter(), [], [], 0
    for q in load_golden():
        seen_as = PolicyLayer(layer, policy_for(q.role, q.region or None), con)
        local = run_agent(q.question, metrics_first_prompt(catalog(seen_as)), model, PolicyToolbox(con, seen_as), 4)
        trace, calls = await ask_through_server(build_server(q.role, q.region or None, con, layer), q.question, model)
        outcomes = [grade(q, t.answer, golden_result(con, q)) for t in (local, trace)]
        counts[q.split, q.kind, "questions"] += 1
        counts[q.split, q.kind, "correct"] += outcomes[1] == "correct"
        errors += any("is_error" in c for c in calls)
        if outcomes[0] != outcomes[1]:
            changed.append(f"{q.question_id} ({q.split}, {q.kind}): {outcomes[0]} in process, "
                           f"{outcomes[1]} over MCP, by {trace.steps[-2].tool}")
            details += [f"{q.question_id} first request's filters: {trace.steps[0].arguments['filters']}",
                        f"{q.question_id} asked: {trace.answer.reason.splitlines()[0]}"]
        if q.question_id == "gq-017":
            print(f"gq-017 calls: {', '.join(calls)}")
    for split in ("dev", "test"):
        for kind in ("answer", "decline", "forbidden"):
            print(f"{split} {kind} correct over MCP: {counts[split, kind, 'correct']} of "
                  f"{counts[split, kind, 'questions']}")
    print(f"runs with a tool error: {errors}")
    total = len(load_golden())
    print(f"same outcome as in process: {total - len(changed)} of {total}")
    print("\n".join(changed + details) or "no outcome changed")   # one line per changed question, then details


anyio.run(main)
