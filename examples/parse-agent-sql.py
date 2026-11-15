"""Parse the SQL the model wrote for gq-017 before it runs: its tree, the tables it reads, a column the guard refuses, and
two inputs that don't parse as one query. The prose's examples of each come from these printed lines."""
import duckdb
import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from lib.context import LAYERS, build_context
from lib.golden import load_golden
from lib.model import RecordedModel
from lib.prompts import layered_sql_messages
from lib.sql_guard import GuardError, allowed_schema, check
from lib.tools import extract_sql
from lib.warehouse import agent_warehouse, connect

con = connect()
question = next(q for q in load_golden() if q.question_id == "gq-017")
context = build_context(con, question.question, LAYERS)          # chapter 4's context, every layer
sql = extract_sql(RecordedModel("context-layers").complete(layered_sql_messages(context.text, question.question)))
print(f"question: {question.question}\n{sql}")

tree = sqlglot.parse_one(sql, read="duckdb")
print("root:", type(tree).__name__)
print("tables read:", ", ".join(f"{t.db}.{t.name} AS {t.alias}" for t in tree.find_all(exp.Table)))
print("columns named:", ", ".join(sorted({f"{c.table}.{c.name}" for c in tree.find_all(exp.Column) if c.table})))

try:
    check(sql, allowed_schema(agent_warehouse(con)))       # the allowlist: the agent's database's tables
except GuardError as e:
    print("guard refuses:", e.kind)
    # the refusal, then the columns of each table it reads, after a fixed phrase
    message, columns = str(e).split(". The tables it reads have only these columns: ")
    print("guard message:", message)
    print("message then lists the columns of:", ", ".join(part.split(" has ")[0] for part in columns.split("; ")))
try:
    con.execute(sql)
except duckdb.Error as e:
    print("DuckDB, had it run:", str(e).splitlines()[0])

statements = sqlglot.parse("SELECT 1; DROP TABLE analytics.fct_orders", read="duckdb")
print("statements in one string:", ", ".join(type(s).__name__ for s in statements))
try:
    sqlglot.parse_one("SELECT region, sum(net_revenue_eur FROM analytics.fct_orders GROUP BY region", read="duckdb")
except ParseError as e:
    error = e.errors[0]                     # the parser's first problem; line and col count from 1
    print("parse error fields:", ", ".join(sorted(error)))
    print(f"parse error: {error['description']}\nparse error line: {error['line']}\nparse error column: {error['col']}")
