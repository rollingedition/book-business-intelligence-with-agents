"""Transpile the guard's SQL to Snowflake: the quoted table name Snowflake reads, a weekday function that answers differently,
and a histogram that passes through unchanged. The printed lines are the output the prose quotes."""
from lib.sql_guard import SqlGuard, transpile
from lib.warehouse import agent_warehouse, connect

con = connect()
guard = SqlGuard(agent_warehouse(con))
WEEKDAYS = """SELECT dayname(order_date_local) AS weekday, strftime(order_date_local, '%Y-%m') AS month,
       round(sum(net_revenue_eur), 2) AS net_revenue
FROM analytics.fct_orders
WHERE status <> 'cancelled' AND year(order_date_local) = 2025
GROUP BY ALL ORDER BY month, weekday"""
checked = guard.check(WEEKDAYS)
print("kept quoted, Snowflake reads:", transpile(checked.sql, "snowflake", quoted=True).sql.split(" FROM ")[1].split(" WHERE")[0])   # the FROM clause only

snowflake = transpile(checked.sql, "snowflake", pretty=True)
print(snowflake.sql)
print("functions passed through unchanged:", ", ".join(snowflake.passed_through) or "none")
print("DuckDB's first weekday:", guard.run(WEEKDAYS).rows[0][0])

MIX = """SELECT region, histogram(channel) AS orders_by_channel FROM analytics.fct_orders
WHERE year(order_date_local) = 2025 GROUP BY region"""
mix = transpile(guard.check(MIX).sql, "snowflake")
print("channel mix in Snowflake:", mix.sql.split(" FROM")[0])   # the SELECT list, which holds the function
print("functions passed through in the channel mix:", ", ".join(mix.passed_through) or "none")
