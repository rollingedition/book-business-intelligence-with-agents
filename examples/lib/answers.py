"""What the agent returns: an `Answer`, which is either a result with its provenance or a reason it can't be given.

An answer always says where it came from (`answer.provenance`): whether a defined metric or a SQL query produced it,
the exact SQL that ran, the filters, the role it was computed for and how fresh the data was. An answer that can't be
given carries its `reason` instead of rows, so declining is an answer like any other.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class Provenance:
    source: str                       # "metric" or "sql"; without a result, "none", "ask_back" or "step_limit"
    sql: str                          # the SQL that ran
    metric: str | None = None         # the metric's name, when a metric produced the answer
    filters: dict = field(default_factory=dict)
    role: str = "analyst"
    data_as_of: str | None = None     # when the newest row the answer read was loaded

    def describe(self) -> str:
        lines = [f"source: {self.source}" + (f" ({self.metric})" if self.metric else ""),
                 f"filters: {self.filters or 'none'}", f"role: {self.role}", f"data as of: {self.data_as_of}"]
        return "\n".join(lines)


@dataclass(frozen=True)
class Answer:
    columns: tuple[str, ...] = ()
    rows: tuple[tuple, ...] = ()
    provenance: Provenance | None = None
    reason: str | None = None         # set when the answer can't be given

    @property
    def answered(self) -> bool:
        return self.reason is None

    @classmethod
    def decline(cls, reason: str, role: str = "analyst") -> "Answer":
        return cls(reason=reason, provenance=Provenance(source="none", sql="", role=role))

    @classmethod
    def step_limit(cls, reason: str, role: str = "analyst") -> "Answer":
        """A run that ran out of model calls: no answer, but not a decline the model chose."""
        return cls(reason=reason, provenance=Provenance(source="step_limit", sql="", role=role))

    @property
    def hit_step_limit(self) -> bool:
        return self.provenance is not None and self.provenance.source == "step_limit"

    def show(self) -> str:
        """The answer as a small text table, or the reason it can't be given."""
        if not self.answered:
            return f"cannot answer: {self.reason}"
        return format_table(self.columns, self.rows)


def format_value(value) -> str:
    if isinstance(value, (Decimal, float)):
        return f"{value:,.2f}"
    return "NULL" if value is None else str(value)


def format_table(columns, rows, limit: int = 12) -> str:
    """Rows as aligned text, at most `limit` of them."""
    cells = [list(map(str, columns))] + [[format_value(v) for v in row] for row in rows[:limit]]
    widths = [max(len(r[i]) for r in cells) for i in range(len(columns))]
    lines = ["  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip() for row in cells]
    if len(rows) > limit:
        lines.append(f"... {len(rows) - limit} more rows")
    return "\n".join(lines)
