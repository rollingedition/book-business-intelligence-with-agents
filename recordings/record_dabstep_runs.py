"""Record the pinned model answering the DABstep subset's three tasks with schema-only SQL, as chapter 3 compares.

For each task, `answer_task()` in examples/lib/dabstep.py makes two calls: the model writes SQL from the payments
table's schema (`DABSTEP_SQL` in examples/lib/prompts.py), the SQL runs on the subset, and the model gives a final
answer from the result in the task's format (`DABSTEP_FINAL`). Six calls in all, in one part:

    python recordings/fetch_dabstep_subset.py     # once, if examples/data/dabstep/ is missing
    python recordings/record_dabstep_runs.py

Outputs go to examples/data/recorded/dabstep-runs/, with manifest.json. Tasks already recorded are skipped.
"""
from local_model import REPO_ROOT, LocalModel, Recorder, recorded_questions, write_part

from lib.dabstep import REVISION, answer_task, connect, load_tasks
from lib.prompts import DABSTEP_FINAL, DABSTEP_SQL, prompt_sha256

NAME = "dabstep-runs"


def main() -> None:
    folder = REPO_ROOT / "examples" / "data" / "recorded" / NAME
    done = {call["question_id"] for call in recorded_questions(folder, 1)}
    con, model, calls = connect(), LocalModel(max_tokens=384), []
    for task in load_tasks():
        if f"dabstep-{task.task_id}" not in done:
            answer_task(con, Recorder(model, f"dabstep-{task.task_id}", calls), task)
    write_part(folder, 1, calls, {
        "script": "recordings/record_dabstep_runs.py",
        "prompt": "DABSTEP_SQL, then DABSTEP_FINAL (examples/lib/prompts.py)",
        "prompt_sha256": prompt_sha256(DABSTEP_SQL + DABSTEP_FINAL),
        "dataset": f"adyen/DABstep@{REVISION}, subset in examples/data/dabstep/",
    }, model)


if __name__ == "__main__":
    main()
