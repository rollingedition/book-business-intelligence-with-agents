"""Record chapter 8's declining agent once on the held-out test split, for chapter 10's final test numbers.

Each run sends the declining prompt (`DECLINING` in examples/lib/prompts.py, filled with `catalog()` from
examples/lib/metric_tools.py) and one golden question to `run_agent()` in examples/lib/agent.py, with the tools of
`DecliningToolbox` from examples/lib/declining.py. The loop calls the model until a tool returns an answer, at most
four times, as in chapter 6. Every call is saved.

The prompt, tools and limit are `record_decline_runs.py`'s, unchanged. Only the test split's answer and decline
questions are recorded, 21 of them: forbidden questions are chapter 9's, decided below the model. The test split was
recorded once, after every chapter's prompts were final, and nothing was changed after it. Run one part at a time; each
part holds seven questions, so at most 28 calls, within the 10-minute budget:

    python recordings/record_decline_test.py --part 1     # parts 1-3: seven test questions each

A part records the questions in its range that it hasn't recorded yet, so earlier replies never change, and saves
after every question. A part with nothing left to record only merges its fields into the manifest. Outputs go to
examples/data/recorded/decline-runs-test/, with manifest.json.
"""
import argparse

from local_model import REPO_ROOT, LocalModel, Recorder, recorded_questions, write_part

from lib.agent import run_agent
from lib.declining import DecliningToolbox
from lib.golden import load_golden
from lib.metric_tools import catalog
from lib.prompts import DECLINING, declining_prompt, prompt_sha256
from lib.semantic import load
from lib.warehouse import connect

NAME = "decline-runs-test"
PER_PART = 7
MAX_STEPS = 4
TUNING = ("Recorded once for chapter 10, with the DECLINING prompt unchanged since decline-runs: a part only adds "
          "the questions it doesn't hold, and no part has been re-recorded. Nothing was tuned on these runs.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--part", type=int, required=True, choices=range(1, 4))
    part = parser.parse_args().part
    in_scope = [q for q in load_golden() if q.split == "test" and q.kind in ("answer", "decline")]
    start = (part - 1) * PER_PART
    folder = REPO_ROOT / "examples" / "data" / "recorded" / NAME
    done = {call["question_id"] for call in recorded_questions(folder, part)}
    questions = [q for q in in_scope[start:start + PER_PART] if q.question_id not in done]
    con, layer = connect(), load()
    system = declining_prompt(catalog(layer))
    model = LocalModel(max_tokens=256)
    fields = {
        "script": "recordings/record_decline_test.py",
        "prompt": "DECLINING (examples/lib/prompts.py), filled by declining_prompt() with catalog() "
                  "from examples/lib/metric_tools.py",
        "prompt_sha256": prompt_sha256(DECLINING),
        "system_prompt_sha256": prompt_sha256(system),
        "max_model_calls_per_question": MAX_STEPS,
        "splits": "parts 1-3: the test split's answer and decline questions, once; forbidden not recorded",
        "tuning": TUNING,
    }
    for q in questions:
        calls = []
        run_agent(q.question, system, Recorder(model, q.question_id, calls), DecliningToolbox(con, layer, role=q.role),
                  max_steps=MAX_STEPS)
        write_part(folder, part, calls, fields, model)
    if not questions:
        write_part(folder, part, [], fields, model)


if __name__ == "__main__":
    main()
