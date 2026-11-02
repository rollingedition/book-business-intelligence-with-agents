"""The five ways schema-only SQL returns a plausible wrong number on the shop's warehouse, found by comparing a query
with its golden SQL.

Chapter 2 names five kinds of failure. `failure_kinds(sql, golden_sql)` parses both queries with sqlglot and reports
each kind whose mark is in the query and not in the golden SQL:

- fan-out: a sum or average of an order-level amount in a query that joins order lines in the same SELECT, so each
  order's amount counts once per line;
- definition: gross revenue where the golden SQL uses net revenue;
- time: the UTC timestamp `placed_at` where the golden SQL uses the local business day, or no fiscal column where
  the golden SQL filters on the fiscal calendar;
- tempting table: `analytics.orders_legacy`, the older mart with the old revenue definition;
- unwritten filter: no condition on `status` where the golden SQL leaves out cancelled orders, or raw orders read
  without the `is_test` flag where the golden SQL reads the marts.

These are the book's own rules, written for this warehouse's traps. They know nothing about other warehouses, and a
query can have a kind and still return the golden result by chance.
"""
from __future__ import annotations

import sqlglot
from sqlglot import exp

KINDS = ("fan-out", "definition", "time", "tempting table", "unwritten filter")

ORDER_LEVEL_AMOUNTS = {"net_revenue_eur", "gross_revenue_eur", "revenue"}
LINE_TABLES = {"analytics.fct_order_lines", "raw.order_lines"}
FISCAL_COLUMNS = {"fiscal_year", "fiscal_quarter", "fiscal_month"}


def _parse(sql: str) -> exp.Expression:
    return sqlglot.parse_one(sql, read="duckdb")


def _tables(tree: exp.Expression) -> set[str]:
    return {f"{t.db}.{t.name}".lower() for t in tree.find_all(exp.Table)}


def _columns(tree: exp.Expression) -> set[str]:
    return {c.name.lower() for c in tree.find_all(exp.Column)}


def _fans_out(tree: exp.Expression) -> bool:
    """Whether a SELECT both joins order lines and sums or averages an order-level amount."""
    for select in tree.find_all(exp.Select):
        tables = {f"{t.db}.{t.name}".lower() for t in select.find_all(exp.Table)
                  if t.find_ancestor(exp.Select) is select}
        if not tables & LINE_TABLES:
            continue
        for aggregate in select.find_all(exp.Sum, exp.Avg):
            if aggregate.find_ancestor(exp.Select) is select and _columns(aggregate) & ORDER_LEVEL_AMOUNTS:
                return True
    return False


def failure_kinds(sql: str, golden_sql: str) -> list[str]:
    """The kinds of failure in `sql`, judged against `golden_sql`, in the order of `KINDS`."""
    tree, golden = _parse(sql), _parse(golden_sql)
    tables, columns = _tables(tree), _columns(tree)
    golden_tables, golden_columns = _tables(golden), _columns(golden)
    found = set()
    if _fans_out(tree):
        found.add("fan-out")
    if "gross_revenue_eur" in columns and "net_revenue_eur" in golden_columns:
        found.add("definition")
    if "placed_at" in columns and "placed_at" not in golden_columns:
        found.add("time")
    if golden_columns & FISCAL_COLUMNS and not columns & FISCAL_COLUMNS:
        found.add("time")
    if "analytics.orders_legacy" in tables and "analytics.orders_legacy" not in golden_tables:
        found.add("tempting table")
    if "status" in golden_columns and not columns & {"status", "order_status"}:
        found.add("unwritten filter")
    if tables & {"raw.orders", "raw.order_lines"} and "is_test" not in columns and not golden_tables & {"raw.orders"}:
        found.add("unwritten filter")
    return [kind for kind in KINDS if kind in found]
