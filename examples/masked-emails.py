"""Finance's masks on the guarded SQL path, reads that try to get past them, and what support and marketing can't do."""
from lib.policies import PolicyGuard, PolicyLayer, policy_for
from lib.semantic import load
from lib.sql_guard import GuardError, SqlGuard
from lib.warehouse import agent_warehouse, connect

con = agent_warehouse(shop := connect())     # chapter 7: the agent's own database, every allowed mart whole
# Each role's guard runs on the role's own database (chapter 7), with the rewrite on top of it.
guard_for = lambda role: PolicyGuard(agent_warehouse(shop, policy=policy_for(role)), policy=policy_for(role))
finance, analyst = guard_for("finance"), SqlGuard(con)
print(policy_for("finance").describe().splitlines()[1].strip())
print(finance.run("SELECT customer_id, customer_name, email, country FROM analytics.dim_customers "
                  "ORDER BY customer_id LIMIT 2").show())


def run(guard, sql):
    try:
        return str(guard.run(sql).rows[0][0]), ""
    except GuardError as e:
        return f"refused ({e.kind})", str(e)


# Each read uses the email without selecting it. The address is synthetic, on the reserved domain example.com.
target, customers = "customer-00042@example.com", "FROM analytics.dim_customers"
reads = {"a WHERE on the email": f"SELECT count(*) {customers} WHERE email = '{target}'",
         "a LIKE on its first letters": f"SELECT count(*) {customers} WHERE email LIKE 'customer-0004%'",
         "distinct emails": f"SELECT count(DISTINCT email) {customers}",
         "the email's length": f"SELECT max(length(email)) {customers}",
         "the largest group by email": f"SELECT max(n) FROM (SELECT count(*) AS n {customers} GROUP BY email)",
         "the raw table": f"SELECT count(*) FROM raw.customers WHERE lower(email) = '{target}'"}
print(f"reads: {len(reads)}")
for name, sql in reads.items():
    print(f"{name}, analyst: {run(analyst, sql)[0]}")
    print(f"{name}, finance: {run(finance, sql)[0]}")

# Support is denied the money columns; marketing, with a minimum group size, gets no guarded SQL at all.
revenue = "SELECT sum(net_revenue_eur) FROM analytics.fct_orders"
shown, message = run(guard_for("support"), revenue)
listed = [c for c in ("gross_revenue_eur", "net_revenue_eur", "discount_eur", "tax_eur")
          if c in message.split("only these columns:")[-1]]
print(f"support, a revenue column: {shown}")
print(f"support, money columns the refusal lists: {', '.join(listed) or 'none'}")
support = PolicyLayer(load(), policy_for("support"), connect())
print(f"support, revenue metrics in its catalog: {', '.join(m for m in support.metrics if 'revenue' in m) or 'none'}")
print(f"marketing, any SQL: {run(guard_for('marketing'), 'SELECT 1')[0]}")
