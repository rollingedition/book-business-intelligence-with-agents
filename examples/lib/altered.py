"""Edits for altered copies of the shop's warehouse, from chapter 3: each changes the raw tables in one known way.

Pass one to `warehouse.altered_copy()`. Each picks the row it changes with its own seed, from IDs in a fixed order,
so a copy holds the same rows on every run.

- `copy_order(status, seed, units)` adds a second order with the same customer, time and lines as a delivered order
  of 2025 with at least `units` units, under a new ID and with `status`.
- `split_refund(seed)` pays one refund in two parts that add up to it to the cent.
"""
from __future__ import annotations

import random

# Delivered orders of 2025 with at least {units} units, away from the year's edges, so their year is the same in UTC
# and in local time.
ORDERS_2025 = """SELECT order_id FROM raw.orders JOIN raw.order_lines USING (order_id)
WHERE NOT is_test AND status = 'delivered' AND placed_at BETWEEN '2025-01-02' AND '2025-12-30'
GROUP BY order_id HAVING sum(quantity) >= {units} ORDER BY 1"""


def _pick(con, sql: str, seed: int):
    return random.Random(seed).choice([i for (i,) in con.execute(sql).fetchall()])


def copy_order(status: str, seed: int, units: int = 1):
    def edit(con):
        old = _pick(con, ORDERS_2025.format(units=units), seed)
        new = con.execute("SELECT max(order_id) + 1 FROM raw.orders").fetchone()[0]   # above every order, test or not
        con.execute(f"INSERT INTO raw.orders SELECT * REPLACE ({new} AS order_id, '{status}' AS status) "
                    f"FROM raw.orders WHERE order_id = {old}")
        con.execute(f"INSERT INTO raw.order_lines SELECT * REPLACE ({new} AS order_id) "
                    f"FROM raw.order_lines WHERE order_id = {old}")
    return edit


def split_refund(seed: int):
    def edit(con):
        old = _pick(con, "SELECT refund_id FROM raw.refunds ORDER BY 1", seed)
        new = con.execute("SELECT max(refund_id) + 1 FROM raw.refunds").fetchone()[0]
        # the new part takes the remainder, so an odd cent isn't lost to rounding
        con.execute(f"INSERT INTO raw.refunds SELECT * REPLACE ({new} AS refund_id, amount - round(amount / 2, 2) "
                    f"AS amount) FROM raw.refunds WHERE refund_id = {old}")
        con.execute(f"UPDATE raw.refunds SET amount = round(amount / 2, 2) WHERE refund_id = {old}")
    return edit
