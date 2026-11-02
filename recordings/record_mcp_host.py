"""Record the pinned model for chapter 11: the book's agent loop as an MCP host, every tool on the semantic server.

One recording, under examples/data/recorded/:
- `mcp-host-runs`: chapter 6's metrics-first agent (`run_agent` and `METRICS_FIRST`, examples/lib/agent.py and
  prompts.py) for each golden question, with every tool called through an in-memory MCP client on chapter 11's
  server (`build_server` and `ask_through_server` in examples/lib/semantic_server.py), built for the question's
  role. The prompt's catalog comes from the server's `list_metrics`. A call that `metric-agent-runs` or
  `policy-agent-runs` already holds is replayed; only the rest are recorded. They are the calls after a tool error,
  whose text the SDK prefixes with "Error executing tool NAME: ". Part 1 is the dev split, part 2 the test split.

    python recordings/record_mcp_host.py --part 1
    python recordings/record_mcp_host.py --part 2

A part records only the questions it hasn't recorded yet, and saves after each one. It opens no socket.
"""
import argparse

import anyio
from local_model import REPO_ROOT, LocalModel, Recorder, recorded_questions, write_part

from lib.golden import load_golden
from lib.model import MissingRecording, RecordedModels
from lib.prompts import METRICS_FIRST, prompt_sha256
from lib.semantic import load
from lib.semantic_server import ask_through_server, build_server
from lib.warehouse import connect

NAME = "mcp-host-runs"


class FirstFromRecording:
    """Answers from the earlier recordings when they hold the messages, and from the live model otherwise."""

    def __init__(self, recorded: RecordedModels, question_id: str, calls: list[dict], live: dict):
        self.recorded, self.question_id, self.calls, self.live = recorded, question_id, calls, live

    def complete(self, messages: list[dict]) -> str:
        try:
            return self.recorded.complete(messages)
        except MissingRecording:
            self.live.setdefault("model", LocalModel(max_tokens=256))       # loaded only when a call needs it
            return Recorder(self.live["model"], self.question_id, self.calls).complete(messages)


async def record(part: int) -> None:
    folder = REPO_ROOT / "examples" / "data" / "recorded" / NAME
    done = {call["question_id"] for call in recorded_questions(folder, part)}
    con, layer, earlier = connect(), load(), RecordedModels("metric-agent-runs", "policy-agent-runs")
    split, live, servers = {1: "dev", 2: "test"}[part], {}, {}
    for q in load_golden():
        if q.split != split or q.question_id in done:
            continue
        key = (q.role, q.region or None)
        servers.setdefault(key, build_server(*key, con=con, layer=layer))
        calls = []
        await ask_through_server(servers[key], q.question, FirstFromRecording(earlier, q.question_id, calls, live))
        if calls:
            write_part(folder, part, calls, {
                "script": "recordings/record_mcp_host.py",
                "prompt": "METRICS_FIRST (examples/lib/prompts.py) with the catalog from the server's list_metrics; "
                          "calls metric-agent-runs or policy-agent-runs hold are replayed, not recorded",
                "prompt_sha256": prompt_sha256(METRICS_FIRST)}, live["model"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--part", type=int, required=True, choices=[1, 2])
    anyio.run(record, parser.parse_args().part)


if __name__ == "__main__":
    main()
