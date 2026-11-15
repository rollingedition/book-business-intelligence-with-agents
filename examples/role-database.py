"""A role's database, not the guard, decides what the role reads: queries the guard accepts return less from each role's
database than from every mart, and the catalog bypass lists no net_revenue_eur for support. The assert after the bypass's
tables-listed line settles that none of support's tables has the net_revenue_eur column the sum needs."""
import duckdb

from lib.guard_attacks import ATTEMPTS
from lib.policies import policy_for
from lib.sql_guard import SqlGuard
from lib.warehouse import agent_warehouse, connect

shop = connect()
marts = agent_warehouse(shop)                 # every allowed mart, whole: no role's limits
guard = SqlGuard(marts)                       # chapter 7's guard knows tables and columns, not roles
roles = {"EMEA's regional lead": policy_for("regional_lead", "EMEA"), "finance": policy_for("finance"),
         "support": policy_for("support")}
QUERIES = {"EMEA's regional lead": "SELECT count(DISTINCT region) AS regions FROM analytics.fct_orders",
           "finance": "SELECT count(*) AS n FROM analytics.dim_customers WHERE email LIKE 'customer-0004%'",
           "support": "SELECT sum(net_revenue_eur) AS revenue FROM analytics.fct_orders"}


def first_value(con, sql):
    try:
        return con.execute(sql).fetchall()[0][0]          # the first column of the first row
    except duckdb.Error as e:
        return str(e).splitlines()[0]


for role, sql in QUERIES.items():
    database = agent_warehouse(shop, policy=roles[role])     # the role's database: its views of the marts only
    guard.check(sql)                                         # raises if the guard refuses; it doesn't
    print(f"{role}, guard accepts: yes")
    print(f"{role}, every mart: {first_value(marts, sql)}")
    print(f"{role}, role's database: {first_value(database, sql)}")

# A parser bypass a draft of the guard let through: a CTE named like DuckDB's catalog, which lists every table's SQL.
support = agent_warehouse(shop, policy=roles["support"])
# the bypass's rows as text: each table's CREATE statement, as DuckDB's catalog shows it
listed = " ".join(str(row) for row in support.execute(ATTEMPTS["CTE named duckdb_tables"]).fetchall())
print(f"support, catalog bypass, tables listed: {listed.count('CREATE TABLE')}")
assert "net_revenue_eur" not in listed              # the catalog lists no net_revenue_eur for support, which its sum needs
print(f"support, catalog bypass, names a revenue column: {'net_revenue_eur' in listed}")
print(f"support, a write: {first_value(support, 'DELETE FROM analytics.fct_orders')}")
