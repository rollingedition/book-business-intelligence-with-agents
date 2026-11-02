"""Record the pinned model writing SQL from layered context, for chapter 4's measurement of what each layer adds.

Each call sends the layered-context prompt (`LAYERED_SQL` in examples/lib/prompts.py, filled by `build_context()` in
examples/lib/context.py with one layer set) and one golden question of kind `answer`, and saves the reply.

    python recordings/record_context_layers.py --part 1      # dev split, schema only, first half of the questions
    python recordings/record_context_layers.py --part 2      # dev split, schema only, second half
    ...                                                      # parts 3-8: the next layer sets, two halves each
    python recordings/record_context_layers.py --split test --layers schema --part 1
    python recordings/record_context_layers.py --split test --layers schema,columns,glossary --part 2

On the dev split, parts 1 to 8 cover the four layer sets in `LAYER_SETS`, two parts each, so each part stays within
the 10-minute budget. On the test split, `--layers` names the set and `--part` only names the output file; outputs go
to the folder `context-layers-test`. A part records only the questions it hasn't recorded yet, so earlier replies
never change. Outputs go to examples/data/recorded/context-layers{,-test}/, with manifest.json.
"""
import argparse

from local_model import REPO_ROOT, LocalModel, Recorder, recorded_questions, write_part

from lib.context import LAYER_SETS, build_context, layer_set_name
from lib.golden import load_golden
from lib.prompts import LAYERED_SQL, layered_sql_messages, prompt_sha256
from lib.warehouse import connect


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--part", type=int, required=True)
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    parser.add_argument("--layers", help="comma-separated layers (test split only)")
    args = parser.parse_args()
    questions = [q for q in load_golden() if q.split == args.split and q.kind == "answer"]
    if args.split == "dev":
        name, layers = "context-layers", LAYER_SETS[(args.part - 1) // 2]
        half = (len(questions) + 1) // 2
        questions = questions[:half] if args.part % 2 else questions[half:]
    else:
        name, layers = "context-layers-test", tuple(args.layers.split(","))
    folder = REPO_ROOT / "examples" / "data" / "recorded" / name
    done = {call["question_id"] for call in recorded_questions(folder, args.part)}
    questions = [q for q in questions if q.question_id not in done]
    con, model = connect(), LocalModel(max_tokens=384)
    for q in questions:
        calls = []
        context = build_context(con, q.question, layers)
        Recorder(model, q.question_id, calls).complete(layered_sql_messages(context.text, q.question))
        # Saved after every question, so a run stopped at the time limit keeps what it recorded.
        write_part(folder, args.part, calls, {
            "script": "recordings/record_context_layers.py",
            "prompt": "LAYERED_SQL (examples/lib/prompts.py), filled with build_context() from examples/lib/context.py",
            "prompt_sha256": prompt_sha256(LAYERED_SQL),
            "split": args.split,
            f"layers_part_{args.part}": layer_set_name(layers),
        }, model)


if __name__ == "__main__":
    main()
