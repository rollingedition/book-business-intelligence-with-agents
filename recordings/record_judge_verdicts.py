"""Record chapter 10's judge: the pinned model grading the book's own answers, and comparing pairs of decline reasons.

Answers (`JUDGE_ANSWER` in examples/lib/prompts.py): every distinct answer with a number that the recorded agents
gave to an answer question, on both splits: chapter 3's schema-only SQL, chapter 6's metrics-first agent and chapter
8's declining agent, replayed by `replay()` in examples/lib/regressions.py and listed by `recorded_cases()` in
examples/lib/judge.py. The judge never sees the golden result.

Pairs (`JUDGE_PAIR`): every question on which both chapter 6's and chapter 8's agents declined, each pair judged
twice, with chapter 6's reason first and then second.

The judge prompts were written once; no verdict was used to tune them. One fix was made to what the judge is shown:
`shown()` in examples/lib/judge.py sorts the rows of a query without ORDER BY, because unordered rows came back in
another order on replay and the prompt didn't replay. The recording made before that fix was set aside, and every
part was recorded again from scratch with the fix in place. Run one part at a time; each part holds at most nine
cases, one call each, within the 10-minute budget:

    python recordings/record_judge_verdicts.py --part 1     # the answers, then the pairs; --list shows the parts

A part records the cases in its range it doesn't hold yet, saving after each. Outputs go to
examples/data/recorded/judge-verdicts/, with manifest.json.
"""
import argparse

from local_model import REPO_ROOT, LocalModel, Recorder, recorded_questions, write_part

from lib.judge import answer_messages, pair_messages, recorded_cases
from lib.prompts import JUDGE_ANSWER, JUDGE_PAIR, prompt_sha256
from lib.semantic import load
from lib.warehouse import connect

NAME = "judge-verdicts"
PER_PART = 9


def jobs(con, layer) -> list[tuple[str, list[dict]]]:
    """Every judge call, in a fixed order, as (case ID, messages)."""
    answers, pairs = recorded_cases(con, layer)
    return [(c.case_id, answer_messages(c.question, c.answer)) for c in answers] + \
        [(p.case_id, pair_messages(p.question.question, p.first, p.second)) for p in pairs]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--part", type=int)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    con, layer = connect(), load()
    planned = jobs(con, layer)
    parts = {i // PER_PART + 1: planned[i:i + PER_PART] for i in range(0, len(planned), PER_PART)}
    if args.list:
        for number, items in parts.items():
            print(number, ", ".join(case for case, _ in items))
        return
    folder = REPO_ROOT / "examples" / "data" / "recorded" / NAME
    done = {call["question_id"] for call in recorded_questions(folder, args.part)}
    model = LocalModel(max_tokens=256)
    fields = {
        "script": "recordings/record_judge_verdicts.py",
        "prompt": "JUDGE_ANSWER (filled with the glossary) and JUDGE_PAIR (examples/lib/prompts.py)",
        "prompt_sha256": prompt_sha256(JUDGE_ANSWER + JUDGE_PAIR),
        "prompt_sha256_answer": prompt_sha256(JUDGE_ANSWER),
        "prompt_sha256_pair": prompt_sha256(JUDGE_PAIR),
        "cases": len(planned),
        "splits": "answers from both splits, as the agents' recordings hold them; the judge never sees golden results",
        "tuning": "The judge prompts were written once; no verdict was used to change them.",
        "recorded": "Recorded once, in full, from scratch. judge.shown() sorts the rows of a query without ORDER BY, "
                    "so that a replay builds the same prompt; an earlier recording, made before that fix, was set "
                    "aside and none of its calls is kept here.",
    }
    todo = [(case, messages) for case, messages in parts[args.part] if case not in done]
    for case, messages in todo:
        calls = []
        Recorder(model, case, calls).complete(messages)
        write_part(folder, args.part, calls, fields, model)
    if not todo:
        write_part(folder, args.part, [], fields, model)


if __name__ == "__main__":
    main()
