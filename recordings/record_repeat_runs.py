"""Record repeated runs of chapter 6's metrics-first agent and chapter 8's declining agent, one run per seed.

Every other recording samples each call once, with the seed 2718 reset before it. This one runs the same 12 dev
questions again under four more seeds (1, 2, 3 and 4), with the same prompts, tools, sampling and four-call limit as
`record_metrics_first.py` and `record_decline_runs.py`, so chapter 10 has five runs of each question per agent: the
original recording and these four. It also runs the declining agent once more with seed 2718 itself, to measure whether
a run replays byte for byte: if it does, its replies equal those in `decline-runs`.

The 12 questions are every dev answer or decline question that either agent's original run didn't get right (gq-007,
gq-008, gq-012, gq-016, gq-017, gq-018, gq-020), and the first five others in ID order (gq-001 to gq-005). They were
chosen from the outcomes, so they are harder than the split's average.

Several seeds sample the same messages, so each call is saved with its `seed` and `agent`, and
`examples/lib/regressions.py`'s `SeededRecording` replays one agent's calls for one seed. Run one part at a time; each
part holds at most eight runs (at most 32 calls), within the 10-minute budget:

    python recordings/record_repeat_runs.py --part 1     # parts 1-6: metrics-first, seeds 1-4
                                                          # parts 7-12: declining, seeds 1-4
                                                          # parts 13-14: declining, seed 2718 again

A part records the runs in its range it doesn't hold yet and saves after every run. Outputs go to
examples/data/recorded/repeat-runs/, with manifest.json.
"""
import argparse
import json

from local_model import REPO_ROOT, SAMPLING, SEED, LocalModel, Reply, write_part

from lib.agent import run_agent
from lib.declining import DecliningToolbox
from lib.golden import load_golden
from lib.metric_tools import MetricToolbox, catalog
from lib.prompts import DECLINING, METRICS_FIRST, declining_prompt, messages_sha256, metrics_first_prompt, prompt_sha256
from lib.semantic import load
from lib.warehouse import connect

NAME = "repeat-runs"
QUESTIONS = ("gq-001", "gq-002", "gq-003", "gq-004", "gq-005", "gq-007", "gq-008", "gq-012", "gq-016", "gq-017",
             "gq-018", "gq-020")
SEEDS = (1, 2, 3, 4)
PER_PART = 8
MAX_STEPS = 4


def runs() -> dict[int, list[tuple[str, int, str]]]:
    """Each part's runs, as (agent, seed, question ID)."""
    planned = [("metrics-first", s, q) for s in SEEDS for q in QUESTIONS] + \
              [("declining", s, q) for s in SEEDS for q in QUESTIONS] + [("declining", SEED, q) for q in QUESTIONS]
    return {i // PER_PART + 1: planned[i:i + PER_PART] for i in range(0, len(planned), PER_PART)}


class SeededModel(LocalModel):
    """The pinned model with the seed chosen per call instead of the book's fixed one."""

    seed = SEED

    def complete(self, messages: list[dict]) -> Reply:
        import time
        prompt = self.render(messages)
        start = time.perf_counter()
        out = self.llm.create_completion(prompt, max_tokens=self.max_tokens, seed=self.seed, stop=["<|im_end|>"],
                                         **SAMPLING)
        usage = out["usage"]
        return Reply(out["choices"][0]["text"], round(time.perf_counter() - start, 1), usage["prompt_tokens"],
                     usage["completion_tokens"])


class SeedRecorder:
    def __init__(self, model: SeededModel, agent: str, question_id: str, calls: list[dict]):
        self.model, self.agent, self.question_id, self.calls = model, agent, question_id, calls

    def complete(self, messages: list[dict]) -> str:
        reply = self.model.complete(messages)
        self.calls.append({"agent": self.agent, "seed": self.model.seed, "question_id": self.question_id,
                           "messages_sha256": messages_sha256(messages), "reply": reply.text,
                           "seconds": reply.seconds, "prompt_tokens": reply.prompt_tokens,
                           "completion_tokens": reply.completion_tokens})
        print(f"{self.agent} seed {self.model.seed} {self.question_id}: {reply.seconds} s", flush=True)
        return reply.text


def main() -> None:
    parser = argparse.ArgumentParser()
    plan = runs()
    parser.add_argument("--part", type=int, required=True, choices=sorted(plan))
    part = parser.parse_args().part
    folder = REPO_ROOT / "examples" / "data" / "recorded" / NAME
    path = folder / f"part-{part}.jsonl"
    held = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
    done = {(c["agent"], c["seed"], c["question_id"]) for c in held}
    todo = [r for r in plan[part] if r not in done]
    con, layer = connect(), load()
    golden = {q.question_id: q for q in load_golden()}
    agents = {"metrics-first": (metrics_first_prompt(catalog(layer)), MetricToolbox),
              "declining": (declining_prompt(catalog(layer)), DecliningToolbox)}
    model = SeededModel(max_tokens=256)
    fields = {
        "script": "recordings/record_repeat_runs.py",
        "prompt": "METRICS_FIRST and DECLINING (examples/lib/prompts.py), filled with catalog() from "
                  "examples/lib/metric_tools.py",
        "prompt_sha256": prompt_sha256(METRICS_FIRST + DECLINING),
        "prompt_sha256_metrics_first": prompt_sha256(METRICS_FIRST),
        "prompt_sha256_declining": prompt_sha256(DECLINING),
        "max_model_calls_per_question": MAX_STEPS,
        "question_ids_planned": list(QUESTIONS),
        "seeds": list(SEEDS) + [SEED],
        "seed_note": "sampling.seed is the default seed; each call's own seed is in its line. Seeds 1-4 for both "
                     "agents; seed 2718 again for the declining agent, to compare with decline-runs.",
        "splits": "dev only; no test question is recorded",
    }
    for agent, seed, question_id in todo:
        system, Toolbox = agents[agent]
        q = golden[question_id]
        model.seed = seed
        calls = []
        run_agent(q.question, system, SeedRecorder(model, agent, question_id, calls),
                  Toolbox(con, layer, role=q.role), max_steps=MAX_STEPS)
        write_part(folder, part, calls, fields, model)
    if not todo:
        write_part(folder, part, [], fields, model)


if __name__ == "__main__":
    main()
