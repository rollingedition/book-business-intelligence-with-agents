"""Record the pinned model writing SQL from the warehouse's schema alone, one call per golden question.

Each call sends the schema-only prompt (`SCHEMA_ONLY_SQL` in examples/lib/prompts.py, filled with the warehouse's
schema) and one golden question, and saves the reply. Run one part at a time, each within the 10-minute budget:

    python recordings/record_schema_only_sql.py --part 1     # gq-001 to gq-024
    python recordings/record_schema_only_sql.py --part 2     # gq-025 to gq-048

A part records the golden questions in its range whose exact messages it hasn't recorded yet, so earlier replies
never change, and a reworded question gets a new reply beside the old one. `--limit N` records at most N of them, for a machine where a whole part takes over 10 minutes.
Outputs go to examples/data/recorded/schema-only-sql/, with manifest.json.
"""
import argparse

from local_model import REPO_ROOT, LocalModel, Recorder, recorded_questions, write_part

from lib.golden import load_golden
from lib.prompts import SCHEMA_ONLY_SQL, messages_sha256, prompt_sha256, schema_only_messages
from lib.warehouse import connect, describe_schema

NAME = "schema-only-sql"
PER_PART = 24


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--part", type=int, required=True)
    parser.add_argument("--limit", type=int, default=PER_PART)
    args = parser.parse_args()
    part = args.part
    wanted = {f"gq-{n:03d}" for n in range((part - 1) * PER_PART + 1, part * PER_PART + 1)}
    folder = REPO_ROOT / "examples" / "data" / "recorded" / NAME
    done = {call["messages_sha256"] for call in recorded_questions(folder, part)}
    schema = describe_schema(connect())
    questions = [q for q in load_golden() if q.question_id in wanted
                 and messages_sha256(schema_only_messages(schema, q.question)) not in done][:args.limit]
    model, calls = LocalModel(max_tokens=384), []
    for q in questions:
        Recorder(model, q.question_id, calls).complete(schema_only_messages(schema, q.question))
    write_part(folder, part, calls, {
        "script": "recordings/record_schema_only_sql.py",
        "prompt": "SCHEMA_ONLY_SQL (examples/lib/prompts.py), filled with describe_schema()",
        "prompt_sha256": prompt_sha256(SCHEMA_ONLY_SQL.format(schema=schema)),
    }, model)


if __name__ == "__main__":
    main()
