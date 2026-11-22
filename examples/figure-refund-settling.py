"""Draw the share of refunds that have come, by days from the order, for orders placed before March 2026, whose refunds have all had time to come.
The prose rests on the share at the window, which is the longest delay: every refund has come by then, and not a day earlier."""
import lib  # noqa: F401  (first, so threads and seeds are fixed before any numerical library loads)
from collections import Counter

from lib.declining import _JOINED, _LAG, SETTLING_DAYS
from lib.figures import ACCENT, INK, MUTED, new_figure, save
from lib.warehouse import connect

con = connect()
# _JOINED is the refunds joined to their orders, and _LAG is the days from the order's local day to the refund's day:
# the same join and lag stale-refunds uses, declared in lib.declining.
lags = [d for (d,) in con.execute(f"SELECT {_LAG} {_JOINED} WHERE o.order_date_local < DATE '2026-03-01'").fetchall()]
n = len(lags)
longest = max(lags)
assert longest == SETTLING_DAYS["order_refunds"]   # the window the refund-rate check uses is this longest delay
counts = Counter(lags)
days = list(range(longest + 1))
share, running = [], 0
for day in days:                                    # a refund counts from the day it came, so the share never falls
    running += counts[day]
    share.append(running / n)
assert share[-1] == 1 and share[-2] < 1   # every refund has come on the window's last day, and not a day before

fig, ax = new_figure(height=2.8)
ax.step(days, share, where="post", color=ACCENT, label="refunds that have come, orders placed before March 2026")
ax.axvline(longest, color=MUTED, linestyle="--", linewidth=1, zorder=1, label=f"settling window, {longest} days")  # behind the curve, so its last rise shows
ax.set_xlabel("days from the order to the refund")
ax.set_ylabel("share of refunds that have come")
ax.set_xlim(0, longest + 1)
ax.set_ylim(0, 1)
ax.yaxis.set_major_formatter(lambda y, _: f"{y:.0%}")
ax.legend(frameon=False, loc="upper left")
save(fig, "refund-settling")

print(f"refunds drawn: {n}")
print(f"longest days: {longest}")
print(f"share of refunds that have come at the window: {share[-1]:.0%}")
