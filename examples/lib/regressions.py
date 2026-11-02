"""Chapter 10's measurements: replay the book's agents, score a run on several measures, and compare two configurations.

`replay()` runs one of the book's agents over golden questions from its recordings and returns one `Run` per question:
its answer, `grade()`'s outcome, and the model calls, seconds and prompt tokens the recording holds for it. The agents
are chapter 3's schema-only SQL (`schema-only-sql`), chapter 6's metrics-first agent (`metric-agent-runs`) and
chapter 8's declining agent (`decline-runs`, and `decline-runs-test` for the test split).

`Scorecard` reports a set of runs on more than accuracy: accuracy with a Wilson interval, chapter 8's decline
measures, the step limits, and the cost of a question in calls, seconds and tokens.

`SeededRecording` replays `repeat-runs`, which holds the same questions sampled under several seeds, one seed at a
time. `compare()` pairs two configurations question by question over their repeated runs, and `gate()` turns the
comparison into a decision a CI job can act on.
"""
from __future__ import annotations

import atexit
import json
import math
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from .agent import run_agent
from .answers import Answer
from .declining import DecliningToolbox, Tally
from .golden import GoldenQuestion, golden_result, grade
from .metric_tools import MetricToolbox, catalog
from .model import RECORDED, MissingRecording, RecordedModel, RecordedModels
from .prompts import declining_prompt, messages_sha256, metrics_first_prompt, schema_only_messages
from .semantic import SemanticLayer
from .tools import extract_sql, run_sql
from .warehouse import READ_ONLY_SETTINGS, build, describe_schema

RECORDINGS = {"schema-only": ("schema-only-sql",), "metrics-first": ("metric-agent-runs",),
              "declining": ("decline-runs", "decline-runs-test")}
MAX_STEPS = 4                         # chapters 6 and 8 record at most four model calls per question
ORIGINAL_SEED = 2718                  # the seed every other recording reset before each call


class Meter:
    """Wraps a recorded model and adds up what the recorded calls cost: calls, seconds and prompt tokens."""

    def __init__(self, model):
        self.model, self.calls, self.seconds, self.tokens = model, 0, 0.0, 0

    def complete(self, messages: list[dict]) -> str:
        call = self.model.call_for(messages)
        self.calls += 1
        self.seconds += call["seconds"]
        self.tokens += call["prompt_tokens"]
        return call["reply"]


class SeededRecording:
    """Replays one agent's calls for one seed from a recording that holds several seeds of the same messages."""

    def __init__(self, agent: str, seed: int, name: str = "repeat-runs"):
        self.name, self.agent, self.seed = name, agent, seed
        folder = RECORDED / name
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        self.calls = {}
        for output in manifest["outputs"]:
            for line in (folder / output).read_text(encoding="utf-8").splitlines():
                call = json.loads(line)
                if call["agent"] == agent and call["seed"] == seed:
                    self.calls[call["messages_sha256"]] = call

    def complete(self, messages: list[dict]) -> str:
        return self.call_for(messages)["reply"]

    def call_for(self, messages: list[dict]) -> dict:
        key = messages_sha256(messages)
        if key not in self.calls:
            raise MissingRecording(f"{self.name} ({self.agent}, seed {self.seed}): no reply for messages {key[:12]}")
        return self.calls[key]


@dataclass
class Run:
    question: GoldenQuestion
    agent: str
    answer: Answer | None             # None when schema-only SQL failed to run
    outcome: str                      # grade()'s outcome, or "error"
    calls: int = 0
    seconds: float = 0.0
    tokens: int = 0


def model_for(agent: str, seed: int = ORIGINAL_SEED):
    """The recorded model for an agent: its original recordings, or `repeat-runs` for another seed."""
    return RecordedModels(*RECORDINGS[agent]) if seed == ORIGINAL_SEED else SeededRecording(agent, seed)


def replay(con: duckdb.DuckDBPyConnection, layer: SemanticLayer, agent: str, questions: list[GoldenQuestion],
           seed: int = ORIGINAL_SEED) -> list[Run]:
    """One run per question, replayed from the agent's recordings."""
    model, runs = model_for(agent, seed), []
    schema = describe_schema(con) if agent == "schema-only" else ""
    system = {"metrics-first": metrics_first_prompt, "declining": declining_prompt}.get(agent, lambda c: "")(
        catalog(layer))
    for q in questions:
        meter = Meter(model)
        if agent == "schema-only":
            try:
                sql = extract_sql(meter.complete(schema_only_messages(schema, q.question)))
                answer = run_sql(con, sql, role=q.role)
                outcome = grade(q, answer, golden_result(con, q))
            except duckdb.Error:
                answer, outcome = None, "error"
        else:
            Toolbox = MetricToolbox if agent == "metrics-first" else DecliningToolbox
            answer = run_agent(q.question, system, meter, Toolbox(con, layer, role=q.role), MAX_STEPS).answer
            outcome = grade(q, answer, golden_result(con, q))
        runs.append(Run(q, agent, answer, outcome, meter.calls, meter.seconds, meter.tokens))
    return runs


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """The Wilson score interval for a proportion k/n, at about 95% for z = 1.96."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


@dataclass
class Scorecard:
    """A set of runs, scored on accuracy with its interval, declines, step limits and cost per question."""
    runs: list[Run]
    tally: Tally = field(default_factory=Tally)

    def __post_init__(self):
        for r in self.runs:
            # A query that failed to run gave no number and chose no decline: Tally counts it with the step limits.
            answer = r.answer or Answer.step_limit("the query failed to run")
            self.tally.add(r.question.question_id, r.question.kind, answer, r.outcome)

    def count(self, outcome: str) -> int:
        return sum(r.outcome == outcome for r in self.runs)

    @property
    def accuracy(self) -> float:
        return self.count("correct") / max(len(self.runs), 1)

    @property
    def interval(self) -> tuple[float, float]:
        return wilson(self.count("correct"), len(self.runs))

    def lines(self, name: str) -> list[str]:
        n, (low, high) = len(self.runs), self.interval
        error_or_limit = self.count("error") + self.count("step limit")
        return [f"{name} correct: {self.count('correct')} of {n}",
                f"{name} accuracy: {self.accuracy:.2f} (95% interval {low:.2f} to {high:.2f})",
                f"{name} wrong numbers: {self.tally.count(ending='wrong')}",
                f"{name} errors or step limits: {error_or_limit}",
                f"{name} decline recall: {self.tally.recall:.2f}",
                f"{name} decline precision: " + (f"{self.tally.precision:.2f}" if self.tally.count(ending="abstained")
                                                 else "no declines"),
                f"{name} coverage: {self.tally.coverage:.2f}",
                f"{name} selective risk: {self.tally.selective_risk:.2f}",
                f"{name} model calls per question: {sum(r.calls for r in self.runs) / n:.1f}",
                f"{name} prompt tokens per question: {sum(r.tokens for r in self.runs) / n:,.0f}"]


@dataclass
class Comparison:
    """Two configurations' repeated runs, paired by question: each question's share of correct runs under each."""
    base: dict[str, list[bool]]
    candidate: dict[str, list[bool]]

    @property
    def questions(self) -> list[str]:
        return sorted(self.base)

    def rate(self, runs: dict[str, list[bool]], question_id: str) -> float:
        return sum(runs[question_id]) / len(runs[question_id])

    def differences(self) -> list[float]:
        return [self.rate(self.candidate, q) - self.rate(self.base, q) for q in self.questions]

    @property
    def mean_difference(self) -> float:
        d = self.differences()
        return sum(d) / len(d)

    @property
    def standard_error(self) -> float:
        """The standard error of the mean paired difference, from the spread of the per-question differences."""
        d, mean = self.differences(), self.mean_difference
        return math.sqrt(sum((x - mean) ** 2 for x in d) / (len(d) - 1) / len(d))

    def half_width(self, level: float = 0.95) -> float:
        """Half the width of the interval: Student's t with n - 1 degrees of freedom times the standard error."""
        return t_quantile(1 - (1 - level) / 2, len(self.questions) - 1) * self.standard_error

    def interval(self, level: float = 0.95) -> tuple[float, float]:
        """The t interval of the mean paired difference. It assumes the mean is roughly normal, which a few dozen
        questions with lumpy differences only approximate; on a dozen it is a rough guide."""
        return self.mean_difference - self.half_width(level), self.mean_difference + self.half_width(level)

    def moved(self, threshold: float = 0.5) -> tuple[list[str], list[str]]:
        """Questions fixed (base below the threshold, candidate at or above it) and broken (the other way)."""
        fixed = [q for q in self.questions
                 if self.rate(self.base, q) < threshold <= self.rate(self.candidate, q)]
        broken = [q for q in self.questions
                  if self.rate(self.candidate, q) < threshold <= self.rate(self.base, q)]
        return fixed, broken

    def sign_test(self) -> float:
        """The exact two-sided sign test on the questions whose share of correct runs changed."""
        d = [x for x in self.differences() if x != 0]
        n, k = len(d), sum(x > 0 for x in d)
        if n == 0:
            return 1.0
        tail = sum(math.comb(n, i) for i in range(min(k, n - k) + 1)) / 2 ** n
        return min(1.0, 2 * tail)

    def stable_breaks(self, was: float = 0.8, now: float = 0.2) -> list[str]:
        """Questions the base got right in at least `was` of its runs and the candidate in at most `now`."""
        return [q for q in self.questions if self.rate(self.base, q) >= was and self.rate(self.candidate, q) <= now]


def t_quantile(p: float, df: int) -> float:
    """The p quantile of Student's t with `df` degrees of freedom, for p above 0.5: the density integrated by
    Simpson's rule and the quantile found by bisection, so that no statistics library is needed."""
    scale = math.exp(math.lgamma((df + 1) / 2) - math.lgamma(df / 2)) / math.sqrt(df * math.pi)

    def cdf(x: float, steps: int = 2000) -> float:
        h = x / steps
        f = [scale * (1 + (i * h) ** 2 / df) ** (-(df + 1) / 2) for i in range(steps + 1)]
        return 0.5 + h / 3 * (f[0] + f[-1] + 4 * sum(f[1:-1:2]) + 2 * sum(f[2:-1:2]))

    low, high = 0.0, 100.0
    for _ in range(60):
        mid = (low + high) / 2
        low, high = (mid, high) if cdf(mid) < p else (low, mid)
    return (low + high) / 2


def smallest_detectable(n: int) -> int | None:
    """The fewest of `n` questions that must turn from always wrong to always right, with the rest unchanged, for the
    gate's interval to exclude zero. Breaks are the mirror image, so the same number fires the mean rule."""
    for k in range(1, n + 1):
        flips = Comparison({f"q{i}": [False] if i < k else [True] for i in range(n)},
                           {f"q{i}": [True] for i in range(n)})
        if flips.interval()[0] > 0:
            return k
    return None


def gate(comparison: Comparison) -> tuple[bool, list[str]]:
    """The book's gate: fail on a stable break, or when the mean paired difference's interval lies below zero."""
    reasons = [f"stable break: {q}" for q in comparison.stable_breaks()]
    low, high = comparison.interval()
    if high < 0:
        reasons.append(f"mean paired difference {comparison.mean_difference:+.2f} (interval {low:+.2f} to {high:+.2f})")
    return not reasons, reasons


def migrated(*statements: str) -> duckdb.DuckDBPyConnection:
    """A new copy of the shop's warehouse with schema changes applied, as an upstream migration would apply them,
    returned read-only like `warehouse.connect()`."""
    folder = Path(tempfile.mkdtemp(prefix="migrated-"))
    atexit.register(shutil.rmtree, folder, ignore_errors=True)
    path = folder / "shop.duckdb"
    build(path)
    with duckdb.connect(str(path)) as writer:
        for statement in statements:
            writer.execute(statement)
    return duckdb.connect(str(path), read_only=True, config=READ_ONLY_SETTINGS)


def schema_checks(con: duckdb.DuckDBPyConnection, layer: SemanticLayer, questions: list[GoldenQuestion],
                  agent: str = "declining") -> dict[str, list[str]]:
    """Three checks a CI job can run on a changed warehouse without calling a model: the golden questions whose SQL
    fails to run, the metrics that fail to compile and run, and the questions whose recorded agent run no longer
    replays, because a tool returned something the model never saw."""
    from .semantic import MetricRequest

    failed: dict[str, list[str]] = {"golden SQL": [], "metrics": [], "replays": []}
    for q in questions:
        try:
            golden_result(con, q)
        except duckdb.Error:
            failed["golden SQL"].append(q.question_id)
    for name in layer.metrics:
        try:
            layer.query(con, MetricRequest(metrics=(name,)))
        except (ValueError, duckdb.Error):
            failed["metrics"].append(name)
    model, system = model_for(agent), declining_prompt(catalog(layer))
    Toolbox = DecliningToolbox if agent == "declining" else MetricToolbox
    if agent == "metrics-first":
        system = metrics_first_prompt(catalog(layer))
    for q in questions:
        if q.kind in ("answer", "decline"):
            try:
                run_agent(q.question, system, model, Toolbox(con, layer, role=q.role), MAX_STEPS)
            except MissingRecording:
                failed["replays"].append(q.question_id)
    return failed
