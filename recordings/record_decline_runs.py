"""Record the pinned model answering golden questions with chapter 8's declining agent: metrics first, typed declines.

Each run sends the declining prompt (`DECLINING` in examples/lib/prompts.py, filled with `catalog()` from
examples/lib/metric_tools.py) and one golden question to `run_agent()` in examples/lib/agent.py, with the tools of
`DecliningToolbox` from examples/lib/declining.py. The loop calls the model until a tool returns an answer, at most
four times, as in chapter 6. Every call is saved.

Only the dev split's answer and decline questions are recorded, 21 of them: forbidden questions are chapter 9's,
decided below the model. Run one part at a time; each part holds seven questions, so at most 28 calls, within the
10-minute budget:

    python recordings/record_decline_runs.py --part 1     # parts 1-3: seven dev questions each

A part records the questions in its range that it hasn't recorded yet, so earlier replies never change, and saves
after every question. A part with nothing left to record only merges its fields into the manifest. Outputs go to
examples/data/recorded/decline-runs/, with manifest.json.
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

NAME = "decline-runs"
PER_PART = 7
MAX_STEPS = 4
TUNING = ("The DECLINING prompt was written from chapter 6's dev traces, then the dev split was recorded with it once: "
          "a part only adds the questions it doesn't hold, and no part has been re-recorded. The prompt was not "
          "changed after recording. No test split is recorded.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--part", type=int, required=True, choices=range(1, 4))
    part = parser.parse_args().part
    in_scope = [q for q in load_golden() if q.split == "dev" and q.kind in ("answer", "decline")]
    start = (part - 1) * PER_PART
    folder = REPO_ROOT / "examples" / "data" / "recorded" / NAME
    done = {call["question_id"] for call in recorded_questions(folder, part)}
    questions = [q for q in in_scope[start:start + PER_PART] if q.question_id not in done]
    con, layer = connect(), load()
    system = declining_prompt(catalog(layer))
    model = LocalModel(max_tokens=256)
    fields = {
        "script": "recordings/record_decline_runs.py",
        "prompt": "DECLINING (examples/lib/prompts.py), filled by declining_prompt() with catalog() "
                  "from examples/lib/metric_tools.py",
        "prompt_sha256": prompt_sha256(DECLINING),
        "system_prompt_sha256": prompt_sha256(system),
        "max_model_calls_per_question": MAX_STEPS,
        "splits": "parts 1-3: the dev split's answer and decline questions; forbidden and test not recorded",
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
