"""Chapter 8's declining agent: it says why a question can't be answered, checks freshness, and is scored on declines.

`DecliningToolbox` keeps chapter 6's metrics-first tools (`lib/metric_tools.py`) and changes two of them:

- `cannot_answer` takes a `kind` from a fixed list, `DECLINE_KINDS`, as well as a reason, so declines can be counted
  by kind. A kind outside the list comes back to the model as an error.
- `query_metric` refuses a request that ranks its result over no period (`unbounded_ranking()`, from chapter 6), and
  sends the refusal back to the model, which can ask the person for a period.
- `query_metric` checks freshness before it answers. For each table a metric reads, `FEEDS` names the feed whose
  `_loaded_at` column says how far its events have arrived. A metric counted on an earlier date than its events, such
  as refunds counted on the order's day, keeps changing after its period ends: `SETTLING_DAYS` says for how long. When
  a feed's newest load came before the period's end plus that window, in UTC at the latest region's offset, the answer
  would be missing rows, so the run ends with a decline of kind `stale`, decided by code, not by the model. The reason
  says whether the missing rows haven't been loaded, haven't happened yet, or both. A request with no period is
  answered, with its data as of in the provenance.

`provenance_card()` prints an answer with everything behind it. `Tally` counts outcomes and computes the measures of
declining: decline precision and recall, coverage, selective risk and a penalty score.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import duckdb

from .answers import Answer, Provenance
from .metric_tools import MetricToolbox, normalize_request, unbounded_ranking, validate_request
from .semantic import MetricRequest, SemanticLayer
from .shop_data import REGION_UTC_OFFSET
from .tools import ToolResult

# The kinds of reason a decline gives. The model may choose the first three; code decides the last two.
DECLINE_KINDS = {
    "not_in_data": "no metric or dimension holds what the question needs",
    "forecast": "the question asks about a period that hasn't happened, or for a prediction",
    "no_definition": "the question uses a term the shop hasn't defined, and no metric settles it",
    "stale": "the data for the period hasn't all arrived: not loaded yet, or not happened yet",
    "forbidden": "the role asking may not see the answer (chapter 9)",
}
MODEL_KINDS = ("not_in_data", "forecast", "no_definition")

# For each table a semantic model reads: the feed whose newest `_loaded_at` says how far its events have arrived.
# A customer's first order date is computed from the orders, so the customers table is as fresh as the orders feed.
FEEDS = {
    "analytics.fct_orders": "analytics.fct_orders",
    "semantic.order_lines": "analytics.fct_order_lines",
    "semantic.refunds": "analytics.fct_refunds",
    "analytics.dim_customers": "analytics.fct_orders",
}

# For each simple metric counted on an earlier date than its feed's events: the days after the period's end that its
# events can still arrive. A refund counted on its order's day comes up to 49 days after the order: every refund on
# orders placed before March 2026 did (`stale-refunds` prints the shares). Other metrics settle when their period ends.
SETTLING_DAYS = {"order_refunds": 49}

# A local day ends this many hours later in UTC in the latest region (AMER), and `_loaded_at` is in UTC.
LATEST_UTC_OFFSET = timedelta(hours=max(REGION_UTC_OFFSET.values()))


def _months_after(day: date, months: int) -> date:
    month = day.month - 1 + months
    return date(day.year + month // 12, month % 12 + 1, 1)


def period_end(grain: str, value) -> date:
    """The first day after the period a metric_time filter value names: "2026-06" at month grain ends on 2026-07-01."""
    if grain == "fiscal_year":                                   # fiscal 2026 runs to January 31, 2026
        return date(int(value), 2, 1)
    if grain == "fiscal_quarter":                                # "2026-Q1" is February to April 2025
        year, quarter = re.fullmatch(r"(\d{4})-Q([1-4])", str(value)).groups()
        return _months_after(date(int(year) - 1, 2, 1), 3 * int(quarter))
    if grain == "year":
        return date(int(value) + 1, 1, 1)
    day = date.fromisoformat(f"{value}-01" if re.fullmatch(r"\d{4}-\d{2}", str(value)) else str(value))
    return {"day": day + timedelta(days=1), "week": day + timedelta(days=7),
            "month": _months_after(day, 1), "quarter": _months_after(day, 3)}[grain]


def request_end(request: MetricRequest) -> date | None:
    """The end of the latest period the request's metric_time filters name, or None when they name no period."""
    ends = [period_end(name.removeprefix("metric_time__"), v)
            for name, value in request.filters.items() if name.startswith("metric_time__")
            for v in (value if isinstance(value, list) else [value])]
    return max(ends, default=None)


@dataclass(frozen=True)
class Freshness:
    table: str                        # the table a metric reads
    feed: str                         # the table whose loads decide its freshness
    loaded_at: datetime               # the feed's newest load
    period_end: date | None           # the first day after the period asked about; None for no period
    settling_days: int = 0            # days after the period's end that its events can still arrive
    as_of: datetime | None = None     # the newest load of any feed: what has happened by now

    @property
    def settles_at(self) -> datetime | None:
        """When every event the period counts has happened: the period's end plus the settling window, as UTC at
        the latest region's offset, so a load at 02:00 UTC doesn't pass for a local day that hasn't ended."""
        if self.period_end is None:
            return None
        return datetime.combine(self.period_end + timedelta(days=self.settling_days), datetime.min.time()) \
            + LATEST_UTC_OFFSET

    @property
    def last_arrival(self) -> date | None:
        """The last local day on which an event the period counts can happen."""
        return None if self.period_end is None else self.period_end + timedelta(days=self.settling_days - 1)

    @property
    def complete(self) -> bool:
        """Whether the feed's newest load came after the period and its settling window ended."""
        return self.settles_at is None or self.loaded_at >= self.settles_at

    @property
    def causes(self) -> list[str]:
        """Why an incomplete period is missing rows: events not loaded yet, events not happened yet, or both."""
        if self.complete:
            return []
        now = self.as_of or self.loaded_at
        return (["not loaded"] if self.loaded_at < min(self.settles_at, now) else []) + \
            (["not happened yet"] if self.settles_at > now else [])

    def describe(self) -> str:
        period = "no period" if self.period_end is None else f"period ends {self.period_end - timedelta(days=1)}"
        if self.settling_days:
            period += f", its rows can arrive through {self.last_arrival} ({self.settling_days} days later)"
        state = "complete" if self.complete else "STALE (" + ", ".join(self.causes) + ")"
        return f"{self.feed} last loaded {self.loaded_at:%Y-%m-%d %H:%M}, {period}: {state}"

    def reason(self) -> str:
        """A sentence for the person: what the feed holds and what the period still needs."""
        text = f"{self.feed} was last loaded at {self.loaded_at:%Y-%m-%d %H:%M}"
        if self.settling_days:
            text += (f", and rows for the period ending {self.period_end - timedelta(days=1)} can arrive through "
                     f"{self.last_arrival}, {self.settling_days} days later")
        else:
            text += f", before the period ended on {self.period_end - timedelta(days=1)}"
        return text + " (" + ", ".join(self.causes) + ")"


def tables_read(layer: SemanticLayer, request: MetricRequest) -> dict[str, int]:
    """The tables the request's metrics aggregate, through their simple metrics, each with its longest settling
    window in days."""
    tables: dict[str, int] = {}
    for m in request.metrics:
        for i in layer.simple_metrics_for(m):
            table = layer.semantic_models[layer.metrics[i.name].semantic_model].table
            tables[table] = max(tables.get(table, 0), SETTLING_DAYS.get(i.name, 0))
    return dict(sorted(tables.items()))


def check_freshness(con: duckdb.DuckDBPyConnection, layer: SemanticLayer, request: MetricRequest) -> list[Freshness]:
    """One freshness check per table the request reads, against the end of the period it asks about plus the
    settling window of the metrics that read it."""
    def newest_load(feed: str) -> datetime:
        (loaded,), = con.execute(f"SELECT max(_loaded_at) FROM {feed}").fetchall()
        return loaded

    end, as_of = request_end(request), max(newest_load(feed) for feed in set(FEEDS.values()))
    return [Freshness(table, FEEDS.get(table, table), newest_load(FEEDS.get(table, table)), end,
                      settling if end else 0, as_of)
            for table, settling in tables_read(layer, request).items()]


# How long refunds take, read from the shop's own data, to set and check `SETTLING_DAYS["order_refunds"]`.
_JOINED = "FROM analytics.fct_refunds AS r JOIN analytics.fct_orders AS o USING (order_id)"
_LAG = "date_diff('day', o.order_date_local, r.refunded_at::DATE)"
_SETTLED = "o.status <> 'cancelled' AND o.order_date_local BETWEEN DATE '2025-05-01' AND DATE '2026-04-30'"


def refund_delays(con: duckdb.DuckDBPyConnection) -> dict[str, float]:
    """Refunds per day, and days from an order to its refund: the median over every refund, and the share within 30
    and 45 days and the longest on orders placed before March 2026, whose refunds have all had time to arrive."""
    (median, per_day), = con.execute(f"SELECT median({_LAG}), count(*) / date_diff('day', min(r.refunded_at), "
                                     f"max(r.refunded_at)) {_JOINED}").fetchall()
    (longest, within_30, within_45), = con.execute(
        f"SELECT max({_LAG}), avg(({_LAG} <= 30)::INT), avg(({_LAG} <= 45)::INT) {_JOINED} "
        "WHERE o.order_date_local < DATE '2026-03-01'").fetchall()
    return {"per day": per_day, "median": median, "within 30": within_30, "within 45": within_45, "longest": longest}


def settled_refund_rate(con: duckdb.DuckDBPyConnection, days_after_end: int | None = None) -> float:
    """The refund rate of the twelve months whose refunds have all come, May 2025 to April 2026, counting only the
    refunds made before `days_after_end` days after each order's month ended, or every refund when it's None."""
    (gross,), = con.execute(f"SELECT sum(gross_revenue_eur) FROM analytics.fct_orders AS o WHERE {_SETTLED}").fetchall()
    before = "TRUE" if days_after_end is None else \
        f"r.refunded_at::DATE < (date_trunc('month', o.order_date_local) + INTERVAL 1 MONTH)::DATE + {days_after_end}"
    (refunded,), = con.execute(f"SELECT sum(r.amount_eur) {_JOINED} WHERE {_SETTLED} AND {before}").fetchall()
    return float(refunded / gross)


def refund_shortfall(con: duckdb.DuckDBPyConnection, period_end: date) -> dict[str, float]:
    """An estimate, from the settled months, of how short a month's refund rate is and why. `period_end` is the first
    day after the month. Refunds made before the refunds feed's last load are loaded; refunds made before the orders
    feed's last load have happened; the rest of the settled rate hasn't happened yet."""
    (loaded,), = con.execute("SELECT max(_loaded_at)::DATE FROM analytics.fct_refunds").fetchall()
    (now,), = con.execute("SELECT max(_loaded_at)::DATE FROM analytics.fct_orders").fetchall()
    settled = settled_refund_rate(con)
    as_loaded = settled_refund_rate(con, (loaded - period_end).days)
    as_happened = settled_refund_rate(con, (now - period_end).days)
    return {"as loaded": as_loaded, "not loaded": as_happened - as_loaded, "not happened": settled - as_happened,
            "share not loaded": (as_happened - as_loaded) / (settled - as_loaded)}


def decline_kind(answer: Answer) -> str | None:
    """The kind a decline gave, read from its reason ("stale: ..."), or None for an answer or another ending."""
    if answer.answered or answer.provenance is None or answer.provenance.source != "none":
        return None
    kind = answer.reason.split(":", 1)[0]
    return kind if kind in DECLINE_KINDS else None


class DecliningToolbox(MetricToolbox):
    """Chapter 6's metric tools, with typed declines, the ranking check and a freshness check before every answer."""

    def __init__(self, con: duckdb.DuckDBPyConnection, layer: SemanticLayer | None = None, role: str = "analyst"):
        super().__init__(con, layer, role)
        self.freshness: list[Freshness] = []          # the checks of the last request that passed validation

    def query_metric(self, arguments: dict) -> ToolResult:
        arguments = {k: [v] if k in ("metrics", "group_by", "order_by") and isinstance(v, str) else v
                     for k, v in arguments.items()}
        try:
            request = normalize_request(MetricRequest.from_arguments(arguments))
        except (TypeError, ValueError) as e:
            return ToolResult(f"error: the request isn't valid: {e}")
        problems = validate_request(self.layer, self.con, request)
        ranking = unbounded_ranking(request) if not problems else None
        if ranking:
            problems = [ranking + "; or ask the person which period they mean"]
        if problems:
            self.rejected.append(problems)
            return ToolResult("error: request rejected: " + "; ".join(problems))
        self.freshness = check_freshness(self.con, self.layer, request)
        stale = [f for f in self.freshness if not f.complete]
        if stale:
            reason = "; ".join(f.reason() for f in stale) + ", so the answer would be missing rows"
            return ToolResult(f"declined: stale: {reason}", Answer.decline(f"stale: {reason}", role=self.role))
        try:
            answer = self.layer.query(self.con, request, role=self.role)
        except (ValueError, duckdb.Error) as e:      # SemanticError is a ValueError
            return ToolResult(f"error: {e}")
        return ToolResult(answer.show(), answer)

    def cannot_answer(self, arguments: dict) -> ToolResult:
        kind, reason = str(arguments.get("kind") or ""), str(arguments.get("reason") or "no reason given")
        if kind not in MODEL_KINDS:
            return ToolResult(f"error: kind must be one of {', '.join(MODEL_KINDS)}; got {kind!r}")
        return ToolResult(f"declined: {kind}: {reason}", Answer.decline(f"{kind}: {reason}", role=self.role))


def provenance_card(answer: Answer, layer: SemanticLayer, freshness: list[Freshness] = (), sql: bool = True) -> str:
    """An answer with what's behind it: the result or the decline, the metric's definition, filters, role,
    freshness and, unless `sql` is false, the SQL that ran."""
    p = answer.provenance
    if not answer.answered:
        ending = {"none": "declined", "ask_back": "asked back", "step_limit": "step limit"}.get(p.source, p.source)
        return f"{ending}: {answer.reason}\nrole: {p.role}"
    lines = [answer.show()]
    for name in (p.metric or "").split(", "):
        if name in layer.metrics:
            lines.append(f"metric: {name}: {layer.metrics[name].description}")
    lines += [f"filters: {p.filters or 'none'}", f"role: {p.role}", f"data as of: {p.data_as_of}"]
    lines += [f"freshness: {f.describe()}" for f in freshness]
    return "\n".join(lines + (["sql:", p.sql] if sql else []))


@dataclass
class Tally:
    """Outcomes over a set of questions, for the measures of declining. A question whose right answer is a decline
    is a positive; an abstention is a run that ended without a number by a decline or a question back."""
    rows: list[tuple[str, str, str]] = field(default_factory=list)   # (question_id, kind, ending)

    def add(self, question_id: str, kind: str, answer: Answer, outcome: str) -> None:
        """Record one run: `outcome` is grade()'s, and the ending is "abstained", "step limit", "right" or "wrong"."""
        if answer.hit_step_limit:
            ending = "step limit"
        elif not answer.answered:
            ending = "abstained"
        else:
            ending = "right" if outcome == "correct" and kind == "answer" else "wrong"
        self.rows.append((question_id, kind, ending))

    def count(self, kind: str | None = None, ending: str | None = None) -> int:
        return sum((kind is None or k == kind) and (ending is None or e == ending) for _, k, e in self.rows)

    @property
    def precision(self) -> float:
        """Of the runs that abstained, the share whose question should be declined."""
        return self.count("decline", "abstained") / max(self.count(ending="abstained"), 1)

    @property
    def recall(self) -> float:
        """Of the questions that should be declined, the share that were."""
        return self.count("decline", "abstained") / max(self.count("decline"), 1)

    @property
    def coverage(self) -> float:
        """The share of questions answered with a number."""
        return (self.count(ending="right") + self.count(ending="wrong")) / max(len(self.rows), 1)

    @property
    def selective_risk(self) -> float:
        """Of the questions answered with a number, the share whose number is wrong."""
        answered = self.count(ending="right") + self.count(ending="wrong")
        return self.count(ending="wrong") / max(answered, 1)

    def penalty_score(self, c: float) -> float:
        """TrustSQL's reliability score, the mean over the questions of each question's score: +1 for a right answer
        or a right decline, 0 for an abstention on an answerable question or a run ended by the step limit, -c for a
        wrong number. Unlike TrustSQL, ambiguous questions are scored too, as questions to decline: a question back
        or a decline on one counts as a right decline."""
        total = self.count(ending="right") + self.count("decline", "abstained") - c * self.count(ending="wrong")
        return total / max(len(self.rows), 1)
