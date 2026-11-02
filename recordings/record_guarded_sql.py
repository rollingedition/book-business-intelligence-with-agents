"""Record the pinned model repairing SQL that the guard refused or DuckDB couldn't run, for chapter 7.

Each run starts from SQL the model already wrote in an earlier recording, for one golden question of kind `answer`:
- `schema-only`: the schema-only prompt (`SCHEMA_ONLY_SQL`), replayed from `schema-only-sql` (chapter 1);
- `layered`: the layered-context prompt with every layer (`LAYERED_SQL`), replayed from `context-layers` and
  `context-layers-test` (chapter 4).
The SQL goes through the guard (`SqlGuard` in examples/lib/sql_guard.py). Only when the guard refuses it, or DuckDB
raises an error, is the live model called, once, with the repair message (`GUARD_REPAIR` in examples/lib/prompts.py)
after its own reply. That repair call is what this script records; the first replies are never recorded again.

    python recordings/record_guarded_sql.py --part 1      # schema-only, dev split
    python recordings/record_guarded_sql.py --part 2      # schema-only, test split
    python recordings/record_guarded_sql.py --part 3      # layered, both splits

A part records only the questions it hasn't recorded yet. Outputs go to examples/data/recorded/guarded-sql-runs/.
"""
import argparse

from local_model import REPO_ROOT, LocalModel, Recorder, recorded_questions, write_part

from lib.context import LAYERS, build_context
from lib.golden import load_golden
from lib.model import MissingRecording, RecordedModels
from lib.prompts import GUARD_REPAIR, layered_sql_messages, prompt_sha256, schema_only_messages
from lib.sql_guard import SqlGuard, answer_with_repair
from lib.warehouse import agent_warehouse, connect, describe_schema

PARTS = {1: ("schema-only", ("dev",)), 2: ("schema-only", ("test",)), 3: ("layered", ("dev", "test"))}


class FirstFromRecording:
    """Answers from the earlier recordings when they hold the messages, and from the live model otherwise."""

    def __init__(self, recorded: RecordedModels, live: Recorder):
        self.recorded, self.live = recorded, live

    def complete(self, messages: list[dict]) -> str:
        try:
            return self.recorded.complete(messages)
        except MissingRecording:
            return self.live.complete(messages)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--part", type=int, required=True, choices=sorted(PARTS))
    args = parser.parse_args()
    context, splits = PARTS[args.part]
    folder = REPO_ROOT / "examples" / "data" / "recorded" / "guarded-sql-runs"
    done = {call["question_id"] for call in recorded_questions(folder, args.part)}
    con = connect()
    guard, schema = SqlGuard(agent_warehouse(con)), describe_schema(con)
    recorded = RecordedModels("schema-only-sql", "context-layers", "context-layers-test")
    model = None
    for q in load_golden():
        if q.kind != "answer" or q.split not in splits or q.question_id in done:
            continue
        if context == "schema-only":
            messages = schema_only_messages(schema, q.question)
        else:
            messages = layered_sql_messages(build_context(con, q.question, LAYERS).text, q.question)
        calls = []
        if model is None:
            model = LocalModel(max_tokens=384)
        answer_with_repair(guard, FirstFromRecording(recorded, Recorder(model, q.question_id, calls)), messages,
                           q.question, role=q.role)
        if calls:     # saved after every question that needed a repair, so a stopped run keeps what it recorded
            write_part(folder, args.part, calls, {
                "script": "recordings/record_guarded_sql.py",
                "prompt": "GUARD_REPAIR (examples/lib/prompts.py), after a first reply replayed from schema-only-sql "
                          "(part 1-2) or context-layers and context-layers-test (part 3), with SqlGuard's message",
                "prompt_sha256": prompt_sha256(GUARD_REPAIR),
                f"context_part_{args.part}": context,
            }, model)


if __name__ == "__main__":
    main()
