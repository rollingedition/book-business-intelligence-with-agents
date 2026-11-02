"""Record the pinned model answering golden questions through the metric tools, with the book's agent loop.

Each run sends the metric-tools prompt (`METRIC_TOOLS` in examples/lib/prompts.py, filled with chapter 1's net revenue
metric) and one golden question to `run_agent()` in examples/lib/agent.py, which calls the model until a tool returns
an answer, at most three times. Every call is saved. Run one part at a time, each within the 10-minute budget:

    python recordings/record_metric_tool_runs.py --part 1     # gq-001 to gq-012

A part records the golden questions in its range that exist and that it hasn't recorded yet, so earlier replies
never change. Outputs go to examples/data/recorded/metric-tool-runs/, with manifest.json.
"""
import argparse

from local_model import REPO_ROOT, LocalModel, Recorder, recorded_questions, write_part

from lib.agent import run_agent
from lib.golden import load_golden
from lib.metrics import METRICS
from lib.prompts import metric_tools_prompt, prompt_sha256
from lib.tools import Toolbox
from lib.warehouse import connect

NAME = "metric-tool-runs"
PER_PART = 12


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--part", type=int, required=True)
    part = parser.parse_args().part
    wanted = {f"gq-{n:03d}" for n in range((part - 1) * PER_PART + 1, part * PER_PART + 1)}
    folder = REPO_ROOT / "examples" / "data" / "recorded" / NAME
    done = {call["question_id"] for call in recorded_questions(folder, part)}
    questions = [q for q in load_golden() if q.question_id in wanted and q.question_id not in done]
    system = metric_tools_prompt(METRICS.values())
    con, model, calls = connect(), LocalModel(max_tokens=256), []
    for q in questions:
        run_agent(q.question, system, Recorder(model, q.question_id, calls), Toolbox(con, role=q.role))
    write_part(folder, part, calls, {
        "script": "recordings/record_metric_tool_runs.py",
        "prompt": "METRIC_TOOLS (examples/lib/prompts.py), filled by metric_tools_prompt() with net_revenue",
        "prompt_sha256": prompt_sha256(system),
        "max_model_calls_per_question": 3,
    }, model)


if __name__ == "__main__":
    main()
