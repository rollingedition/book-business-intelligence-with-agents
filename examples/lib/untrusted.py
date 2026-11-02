"""Text in the data is data: a warehouse value that carries an instruction, and the checks that keep it from mattering.

Once a query has run, an agent often asks the model to write the answer in a sentence or two. The model then reads
the result's values, product names included, in the same context as its instructions, and a value can be written to
look like one. Chapter 9 shows this with one synthetic product in the book's own warehouse:

- `warehouse_with_product_name()` builds a copy of the shop's warehouse in which one product's name is replaced, as a
  catalogue feed or an editor might load it, and reopens it read-only, like `warehouse.connect()`. Nothing leaves the
  machine: the copy lives in a temporary folder and is deleted when the program exits.
- `summary_messages()` builds the summary prompt for a question and its answer, either with the result pasted in, or
  with the result between `<result>` tags and a sentence saying that text inside them is data.
- `unsupported_numbers()` lists every number in a summary that no cell of the answer holds, and `missing_numbers()`
  every number cell of the answer the summary doesn't state. A summary with neither restates the result, nothing
  more and nothing less, so code, not the model, decides whether it may be shown beside the table. The check suits
  small results, and refuses a summary that rounds (253k for 253,328.11) as readily as one that invents.
"""
from __future__ import annotations

import atexit
import re
import shutil
import tempfile
from decimal import Decimal
from pathlib import Path

import duckdb

from .answers import Answer, format_table
from .prompts import ANSWER_SUMMARY, ANSWER_SUMMARY_DELIMITED
from .warehouse import READ_ONLY_SETTINGS, build

NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")


def warehouse_with_product_name(product_name: str, new_name: str) -> duckdb.DuckDBPyConnection:
    """A read-only copy of the warehouse in which the product called `product_name` is called `new_name`."""
    folder = Path(tempfile.mkdtemp(prefix="shop-untrusted-"))
    atexit.register(shutil.rmtree, folder, ignore_errors=True)
    path = folder / "shop.duckdb"
    build(path)
    with duckdb.connect(str(path)) as con:
        changed = con.execute("UPDATE analytics.dim_products SET product_name = $2 WHERE product_name = $1",
                              [product_name, new_name]).fetchall()
        if changed[0][0] != 1:
            raise ValueError(f"expected one product called {product_name!r}, found {changed[0][0]}")
    return duckdb.connect(str(path), read_only=True, config=READ_ONLY_SETTINGS)


def summary_messages(question: str, answer: Answer, delimited: bool = False) -> list[dict]:
    """The messages for one summary call: the summary prompt, then the question and the answer's table."""
    table = format_table(answer.columns, answer.rows)
    if delimited:
        return [{"role": "system", "content": ANSWER_SUMMARY_DELIMITED},
                {"role": "user", "content": f"Question: {question}\n\n<result>\n{table}\n</result>"}]
    return [{"role": "system", "content": ANSWER_SUMMARY},
            {"role": "user", "content": f"Question: {question}\n\nResult:\n{table}"}]


def _number(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


def _cells(answer: Answer) -> list[Decimal]:
    return [Decimal(str(v)).normalize() for row in answer.rows for v in row
            if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)]


def missing_numbers(summary: str, answer: Answer) -> list[str]:
    """Number cells of the answer that the summary doesn't state."""
    stated = {_number(n).normalize() for n in NUMBER.findall(summary)}
    return [f"{v:,}" for v in _cells(answer) if v not in stated]


def summary_supported(summary: str, answer: Answer, ignore: tuple[str, ...] = ()) -> bool:
    """Whether the summary states every number of the answer and no other: the condition for showing it."""
    return not unsupported_numbers(summary, answer, ignore) and not missing_numbers(summary, answer)


def unsupported_numbers(summary: str, answer: Answer, ignore: tuple[str, ...] = ()) -> list[str]:
    """Numbers in the summary that no cell of the answer holds, ignoring those in `ignore` (such as a year asked)."""
    known = set(_cells(answer))
    for row in answer.rows:
        for value in row:
            if isinstance(value, str):
                known |= {_number(n).normalize() for n in NUMBER.findall(value)}
    known |= {_number(n).normalize() for text in ignore for n in NUMBER.findall(text)}
    return [n for n in NUMBER.findall(summary) if _number(n).normalize() not in known]
