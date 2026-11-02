"""Chapter 10's judge: the book's own model, called with a judge prompt, and measured against reference labels.

The judge is the same pinned model as the agent, so it is never trusted on its own. Two prompts in `lib/prompts.py`:

- `JUDGE_ANSWER` grades one answer to a golden question as "correct" or "incorrect", from the question, the role,
  how the answer was computed and its result, with the shop's glossary, and without the golden result.
- `JUDGE_PAIR` compares two reasons for declining the same question and names the better one, "A", "B" or "tie".
  Each pair is judged in both orders, so a verdict that follows the position, not the text, shows.

`parse_verdict()` reads a reply into a `Verdict`; a reply that isn't the JSON asked for becomes "unparsed", which
never counts as agreement. The reference labels for `JUDGE_ANSWER` are not opinions: `reference_label()` is
`results_match()` against the golden result, the check chapter 3 built, so anyone can recompute them.
`agreement()` compares verdicts with reference labels: the share that agree, Cohen's kappa and Scott's pi.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, replace

import sqlglot

from .answers import Answer
from .context import load_glossary
from .golden import GoldenQuestion, _key, _normal, results_match
from .prompts import JUDGE_ANSWER, JUDGE_PAIR

LABELS = ("correct", "incorrect")
FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


@dataclass(frozen=True)
class Verdict:
    label: str                        # one of the labels asked for, or "unparsed"
    reason: str
    reply: str                        # the judge's reply, as recorded


def parse_verdict(reply: str, key: str = "verdict", labels: tuple[str, ...] = LABELS) -> Verdict:
    """The judge's verdict in a reply: `key`'s value if it is one of `labels`, otherwise "unparsed"."""
    try:
        data = json.loads(FENCE.sub("", reply.strip()))
    except json.JSONDecodeError:
        return Verdict("unparsed", "", reply)
    if not isinstance(data, dict):
        return Verdict("unparsed", "", reply)
    label = str(data.get(key, "")).strip()
    label = next((x for x in labels if x.lower() == label.lower()), "unparsed")
    return Verdict(label, str(data.get("reason", "")), reply)


def computed_how(answer: Answer) -> str:
    """How an answer was computed, as the judge sees it: the metric, if one produced it, and the SQL that ran."""
    p = answer.provenance
    return (f"metric: {p.metric}\n" if p.metric else "") + f"SQL:\n{p.sql}"


def shown(answer: Answer) -> Answer:
    """The answer as the judge sees it. A query without ORDER BY returns its rows in no fixed order, which would change
    the prompt from one replay to the next, so its rows are shown sorted."""
    try:
        ordered = sqlglot.parse_one(answer.provenance.sql, read="duckdb").args.get("order") is not None
    except sqlglot.errors.ParseError:
        ordered = False
    if ordered:
        return answer
    return replace(answer, rows=tuple(sorted(answer.rows, key=lambda row: _key(tuple(map(_normal, row))))))


def answer_messages(question: GoldenQuestion, answer: Answer) -> list[dict]:
    """The messages that ask the judge to grade one answer, with the glossary first so calls share it."""
    system = JUDGE_ANSWER.format(glossary="\n".join(f"- {line}" for line in load_glossary()))
    user = (f"Question: {question.question}\nAsked by: {question.role}\n\nHow it was computed:\n{computed_how(answer)}"
            f"\n\nResult:\n{shown(answer).show()}")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def pair_messages(question: str, first: str, second: str) -> list[dict]:
    """The messages that ask the judge which of two decline reasons is better: `first` is shown as A."""
    user = f"Question: {question}\n\nReply A: {first}\n\nReply B: {second}"
    return [{"role": "system", "content": JUDGE_PAIR}, {"role": "user", "content": user}]


def reference_label(question: GoldenQuestion, answer: Answer, golden_rows) -> str:
    """The checkable label: "correct" if the answer's rows match the golden result under the question's rule."""
    match = results_match(answer.rows, golden_rows, question.order_matters, question.tolerance, question.absolute)
    return "correct" if match else "incorrect"


@dataclass(frozen=True)
class JudgeCase:
    case_id: str                      # the question ID and the agent, such as "gq-008 declining"
    question: GoldenQuestion
    answer: Answer
    reference: str                    # reference_label()


def distinct_cases(runs, golden: dict) -> list[JudgeCase]:
    """One case per distinct answer with a number to an answer question: the same SQL for the same question, from
    two agents, is judged once, under the first agent that gave it. `golden` maps question IDs to golden rows."""
    cases, seen = [], set()
    for run in runs:
        q, answer = run.question, run.answer
        if q.kind != "answer" or answer is None or not answer.answered:
            continue
        if (q.question_id, answer.provenance.sql) in seen:
            continue
        seen.add((q.question_id, answer.provenance.sql))
        cases.append(JudgeCase(f"{q.question_id} {run.agent}", q, answer,
                               reference_label(q, answer, golden[q.question_id])))
    return cases


@dataclass(frozen=True)
class Agreement:
    n: int
    observed: float                   # the share of cases where the judge and the reference agree
    chance_kappa: float               # chance agreement from each rater's own label shares
    chance_pi: float                  # chance agreement from the two raters' pooled label shares
    table: dict                       # (reference, verdict) -> count

    @property
    def kappa(self) -> float:
        return (self.observed - self.chance_kappa) / (1 - self.chance_kappa) if self.chance_kappa < 1 else 1.0

    @property
    def pi(self) -> float:
        return (self.observed - self.chance_pi) / (1 - self.chance_pi) if self.chance_pi < 1 else 1.0


def agreement(reference: list[str], verdicts: list[str]) -> Agreement:
    """Observed agreement, and the chance terms of Cohen's kappa and Scott's pi, over paired labels. An "unparsed"
    verdict is a label of its own, so it never agrees with a reference label."""
    n = len(reference)
    labels = sorted(set(reference) | set(verdicts))
    ref, ver = Counter(reference), Counter(verdicts)
    observed = sum(a == b for a, b in zip(reference, verdicts)) / n
    chance_kappa = sum(ref[x] / n * ver[x] / n for x in labels)
    chance_pi = sum(((ref[x] + ver[x]) / (2 * n)) ** 2 for x in labels)
    return Agreement(n, observed, chance_kappa, chance_pi, dict(Counter(zip(reference, verdicts))))


def kappa_one_verdict(reference: list[str], verdicts: list[str]) -> tuple[float, float]:
    """The lowest and highest Cohen's kappa when any one verdict is turned to the other label: how far a single case
    moves a kappa computed on a few dozen cases."""
    other = {"correct": "incorrect", "incorrect": "correct"}
    kappas = [agreement(reference, verdicts[:i] + [other.get(v, "correct")] + verdicts[i + 1:]).kappa
              for i, v in enumerate(verdicts)]
    return min(kappas), max(kappas)


@dataclass(frozen=True)
class PairCase:
    case_id: str                      # the question ID and which agent's reason is shown first, as A
    question: GoldenQuestion
    first: str
    second: str


def decline_reason(answer: Answer) -> str:
    """A decline's reason as the person reads it, without the kind chapter 8's agent puts first."""
    kind, _, rest = answer.reason.partition(": ")
    return rest if rest and kind in ("not_in_data", "forecast", "no_definition") else answer.reason


AGENTS = ("schema-only", "metrics-first", "declining")


def recorded_cases(con, layer) -> tuple[list[JudgeCase], list[PairCase]]:
    """The judge's cases, from the book's recorded runs on both splits' answer and decline questions: every distinct
    answer with a number to an answer question, and, for each question on which both chapter 6's and chapter 8's
    agents declined, their two reasons in both orders."""
    from .golden import golden_result, load_golden
    from .regressions import replay

    questions = [q for q in load_golden() if q.kind in ("answer", "decline")]
    golden = {q.question_id: golden_result(con, q) for q in questions}
    runs = {agent: replay(con, layer, agent, questions) for agent in AGENTS}
    answers = distinct_cases([r for agent in AGENTS for r in runs[agent]], golden)
    pairs = []
    for first, second in zip(runs["metrics-first"], runs["declining"]):
        a, b, q = first.answer, second.answer, first.question
        if a and b and a.provenance.source == "none" and b.provenance.source == "none":
            ra, rb = decline_reason(a), decline_reason(b)
            pairs += [PairCase(f"{q.question_id} pair metrics-first first", q, ra, rb),
                      PairCase(f"{q.question_id} pair declining first", q, rb, ra)]
    return answers, pairs


@dataclass(frozen=True)
class PairResult:
    """One pair judged in both orders, with the verdicts read in the first order's letters (A is metrics-first)."""
    case: PairCase                    # the first order: metrics-first's reason shown as A
    first: Verdict
    second: Verdict

    @property
    def second_as_first(self) -> str:
        return {"A": "B", "B": "A"}.get(self.second.label, self.second.label)

    @property
    def winner(self) -> str | None:
        """The agent whose reason won in both orders, or None when the verdict changed with the order or was a tie."""
        label = self.first.label
        return {"A": "metrics-first", "B": "declining"}.get(label) if label == self.second_as_first else None

    @property
    def longer_won(self) -> bool:
        winner, loser = (self.case.first, self.case.second) if self.first.label == "A" else \
            (self.case.second, self.case.first)
        return self.winner is not None and len(winner) > len(loser)


def judge_pairs(model, pairs: list[PairCase]) -> list[PairResult]:
    """Each pair's two calls, from `recorded_cases()`'s pairs, which come metrics-first first, then declining first."""
    def verdict(p: PairCase) -> Verdict:
        return parse_verdict(model.complete(pair_messages(p.question.question, p.first, p.second)), "better",
                             ("A", "B", "tie"))
    return [PairResult(one, verdict(one), verdict(two)) for one, two in zip(pairs[::2], pairs[1::2])]
