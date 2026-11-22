"""Draw how many 2025 orders have each number of lines, from the join the tent example uses, which counts an order once per line.
The prose rests on `share of orders with one line`, `orders drawn`, `most lines in an order`, and the count at each number of lines."""
import lib  # noqa: F401  (first, so threads and seeds are fixed before any numerical library loads)
from lib.figures import ACCENT, new_figure, save
from lib.warehouse import connect

con = connect()
# The same join and year filter as the tent example, with no product filter: every 2025 order joined to all of its lines.
# count(*) per order is the number of joined rows that carry that order, so its revenue is summed that many times.
per_order = con.execute("""SELECT f.order_id, count(*) AS lines
    FROM analytics.fct_orders f JOIN analytics.fct_order_lines fl ON f.order_id = fl.order_id
    WHERE EXTRACT(YEAR FROM f.placed_at) = 2025
    GROUP BY f.order_id""").fetchall()
orders = len(per_order)
counts = {n: 0 for n in range(1, max(n for _, n in per_order) + 1)}   # every line count from one up, empty ones at zero
for _, n in per_order:
    counts[n] += 1

fig, ax = new_figure(height=2.8)
ax.bar(list(counts), list(counts.values()), color=ACCENT, width=0.7, label="2025 orders, by lines in the order")
ax.set_xticks(list(counts))
ax.set_xlabel("lines in the order, count")
ax.set_ylabel("orders, count")
ax.set_ylim(bottom=0)
ax.legend(frameon=False)
save(fig, "lines-per-order")

print(f"orders drawn: {orders}")
print(f"share of orders with one line: {counts[1] / orders:.1%}")
print(f"most lines in an order: {max(counts)}")
for n, c in counts.items():
    print(f"orders with {n} {'line' if n == 1 else 'lines'}: {c}")
