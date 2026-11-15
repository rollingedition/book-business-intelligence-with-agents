"""Build the shop's warehouse from its seed and list every table with its row count. The point about test orders rests on the `raw.orders` and `analytics.fct_orders` rows; the last two lines give the shop's test orders and its cancelled orders."""
from lib.shop_data import SHOP_SEED
from lib.warehouse import connect, table_sizes

con = connect()                  # generates the shop, loads raw, builds the marts, reopens read-only
print(f"seed: {SHOP_SEED}")
for table, rows in table_sizes(con):
    print(f"{table}: {rows:,}")

# The trailing comma unpacks the one row this query returns. order_date_local is the order's day in its
# region's time zone, the day sales are counted on; is_test marks orders placed from the shop's test accounts.
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
