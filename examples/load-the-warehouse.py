"""Build the shop's warehouse from its seed and list every table with its row count."""
from lib.shop_data import SHOP_SEED
from lib.warehouse import connect, table_sizes

con = connect()                  # generates the shop, loads raw, builds the marts, reopens read-only
print(f"seed: {SHOP_SEED}")
for table, rows in table_sizes(con):
    print(f"{table}: {rows:,}")

(first, last, test_orders, cancelled), = con.execute("""
    SELECT (SELECT min(order_date_local) FROM analytics.fct_orders),
           (SELECT max(order_date_local) FROM analytics.fct_orders),
           (SELECT count(*) FROM raw.orders WHERE is_test),
           (SELECT count(*) FROM analytics.fct_orders WHERE status = 'cancelled')
""").fetchall()
print(f"first order day: {first}")
print(f"last order day: {last}")
print(f"test orders in raw.orders: {test_orders}")
print(f"cancelled orders in fct_orders: {cancelled}")
