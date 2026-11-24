"""Audit every answerable golden SQL for fan-out: a SUM, COUNT or AVG over rows that the gold's own joins repeat.
The prose rests on the golds audited and flagged, and on the planted bad gold, chapter 2's model SQL for gq-007, being flagged."""
from lib.golden import load_golden
from lib.model import RecordedModel
from lib.prompts import schema_only_messages
from lib.semantic import load
from lib.tools import extract_sql
from lib.warehouse import connect, describe_schema
import sqlglot
from sqlglot import exp

con = connect()
keys = load().keys_by_table(con)  # e.g. analytics.fct_orders -> order_id, the primary entity of the orders model

def fan_out(sql):
    """The tables whose key repeats within a group, under the query's own FROM, joins and WHERE."""
    flagged = set()
    for select in sqlglot.parse_one(sql, read="duckdb").find_all(exp.Select):  # the outer query and every subquery
        tables = {t.alias_or_name: f"{t.db}.{t.name}" for t in select.find_all(exp.Table) if t.parent_select is select}
        for agg in select.find_all(exp.Sum, exp.Count, exp.Avg):
            if agg.parent_select is not select or agg.find(exp.Distinct):  # a distinct count can't be inflated
                continue
            column = agg.find(exp.Column)  # COUNT(*) has none: it counts the rows of the first table in FROM
            alias = column.table if column else select.args["from_"].this.alias_or_name
            if tables.get(alias) not in keys:  # a CTE, a derived table or a table no semantic model owns is skipped
                continue
            # The key's columns, qualified with the gold's alias for the measure's table.
            key = keys[tables[alias]].transform(lambda n: exp.column(n.name, table=alias) if isinstance(n, exp.Column) else n)
            # The gold's grouping columns stay first, so its GROUP BY 1 or GROUP BY ALL still groups the probe.
            grouping = [e for e in select.expressions if not e.find(exp.AggFunc)]
            probe = select.copy().select(*grouping, "count(*)", exp.Count(this=exp.Distinct(expressions=[key])), append=False)
            probe = probe.where(exp.Not(this=exp.Is(this=key.copy(), expression=exp.Null())))  # a LEFT JOIN's unmatched rows repeat nothing
            probe.set("order", None), probe.set("limit", None), probe.set("having", None)
            if any(row[-2] > row[-1] for row in con.execute(probe.sql("duckdb")).fetchall()):  # rows, then distinct keys, per group
                flagged.add(tables[alias])
    return sorted(flagged)

golds = [q for q in load_golden() if q.kind == "answer"]
flags = {q.question_id: fan_out(q.golden_sql) for q in golds}
print(f"golds audited: {len(golds)}")
print(f"golds flagged: {sum(bool(tables) for tables in flags.values())}")
print(f"flagged: {', '.join(f'{qid} ({", ".join(tables)})' for qid, tables in flags.items() if tables) or 'none'}")

# The planted bad gold: chapter 2's recorded model SQL for gq-007, which sums each order's revenue over its joined lines.
question = next(q for q in golds if q.question_id == "gq-007")
planted = fan_out(extract_sql(RecordedModel("schema-only-sql").complete(schema_only_messages(describe_schema(con), question.question))))
assert planted, "the planted gold must be flagged"
print(f"planted gq-007 flagged on: {', '.join(planted)}")
