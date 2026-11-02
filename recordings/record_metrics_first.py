"""Record the pinned model answering golden questions metrics first: through the semantic layer's tools, never tables.

Each run sends the metrics-first prompt (`METRICS_FIRST` in examples/lib/prompts.py, filled with `catalog()` from
examples/lib/metric_tools.py) and one golden question to `run_agent()` in examples/lib/agent.py, with the tools of
`MetricToolbox`. The loop calls the model until a tool returns an answer, at most four times. Every call is saved.
Run one part at a time; each part holds six questions, so at most 24 calls, within the 10-minute budget:

    python recordings/record_metrics_first.py --part 1     # parts 1-4: the dev split, six questions each
    python recordings/record_metrics_first.py --part 5     # parts 5-8: the test split, recorded once, for the final number

A part records the questions in its range that it hasn't recorded yet, so earlier replies never change, and saves
after every question. Outputs go to examples/data/recorded/metric-agent-runs/, with manifest.json.
"""
import argparse

from local_model import REPO_ROOT, LocalModel, Recorder, recorded_questions, write_part

from lib.agent import run_agent
from lib.golden import load_golden
from lib.metric_tools import MetricToolbox, catalog
from lib.prompts import METRICS_FIRST, metrics_first_prompt, prompt_sha256
from lib.semantic import load
from lib.warehouse import connect

NAME = "metric-agent-runs"
PER_PART = 6
MAX_STEPS = 4


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--part", type=int, required=True, choices=range(1, 9))
    part = parser.parse_args().part
    split = "dev" if part <= 4 else "test"
    in_split = [q for q in load_golden() if q.split == split]
    start = ((part - 1) % 4) * PER_PART
    folder = REPO_ROOT / "examples" / "data" / "recorded" / NAME
    done = {call["question_id"] for call in recorded_questions(folder, part)}
    questions = [q for q in in_split[start:start + PER_PART] if q.question_id not in done]
    con, layer = connect(), load()
    system = metrics_first_prompt(catalog(layer))
    model = LocalModel(max_tokens=256)
    for q in questions:
        calls = []
        run_agent(q.question, system, Recorder(model, q.question_id, calls), MetricToolbox(con, layer, role=q.role),
                  max_steps=MAX_STEPS)
        write_part(folder, part, calls, {
            "script": "recordings/record_metrics_first.py",
            "prompt": "METRICS_FIRST (examples/lib/prompts.py), filled by metrics_first_prompt() with catalog() "
                      "from examples/lib/metric_tools.py",
            "prompt_sha256": prompt_sha256(METRICS_FIRST),
            "system_prompt_sha256": prompt_sha256(system),
            "max_model_calls_per_question": MAX_STEPS,
            "splits": "parts 1-4: dev; parts 5-8: test",
        }, model)


if __name__ == "__main__":
    main()
