"""The shop's raw data, generated from one fixed seed.

This book follows one case throughout: an online shop that sells outdoor and camping gear in three regions (EMEA,
AMER and APAC). Nothing about the shop is real. This module generates the rows its source systems would have loaded
into the warehouse's `raw` schema; `lib/warehouse.py` loads them into DuckDB and builds the `analytics` marts.

How it stays the same on every machine:
- one seed, `SHOP_SEED`, and Python's own `random.Random`, so no library version can change a row;
- one random stream per table, seeded from the seed and the table's name, so changing how one table is generated
  never moves another table's draws;
- dates fixed between `FIRST_DAY` and `LAST_DAY`; nothing depends on the day it runs.

The data holds the traps a real warehouse has, on purpose: prices that include VAT in EMEA and exclude sales tax
elsewhere, three currencies, test orders, cancelled and returned orders, refunds that land in a later month than
their order, duplicate customers whose emails differ only in case, orders with no channel, timestamps in UTC while
the business counts local days, and a fiscal year that starts on February 1.

Personal details are synthetic and can't reach anyone: a name is a given name from a fixed list and an initial,
emails use the reserved domain example.com (test accounts use test.example.com), only the last two digits of a phone
number exist, and no card or bank numbers are generated.

Every raw table has a `_loaded_at` column: when the nightly load brought the row in (02:00 UTC the day after the
event). The refunds feed stopped after `REFUNDS_LOADED_THROUGH`, so later refunds haven't arrived.
"""
from __future__ import annotations

import bisect
import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

SHOP_SEED = 2718
FIRST_DAY = date(2024, 2, 1)           # the first order
LAST_DAY = date(2026, 6, 30)           # the last order
REFUNDS_LOADED_THROUGH = date(2026, 6, 26)

# country: (region, currency, tax rate, whether prices include the tax)
COUNTRIES = {
    "DE": ("EMEA", "EUR", "0.19", True), "FR": ("EMEA", "EUR", "0.20", True), "NL": ("EMEA", "EUR", "0.21", True),
    "ES": ("EMEA", "EUR", "0.21", True), "GB": ("EMEA", "GBP", "0.20", True),
    "US": ("AMER", "USD", "0.07", False), "CA": ("AMER", "USD", "0.13", False),
    "AU": ("APAC", "USD", "0.10", False), "SG": ("APAC", "USD", "0.09", False), "JP": ("APAC", "USD", "0.10", False),
}
COUNTRY_WEIGHTS = {"DE": 16, "FR": 9, "NL": 6, "ES": 5, "GB": 9, "US": 28, "CA": 7, "AU": 9, "SG": 4, "JP": 7}
# Hours to add to local time to get UTC, ignoring daylight saving: used only to place orders in the local evening.
REGION_UTC_OFFSET = {"EMEA": -1, "AMER": 5, "APAC": -8}

GIVEN_NAMES = [
    "Aino", "Amara", "Ana", "Arjun", "Astrid", "Bea", "Bram", "Caio", "Chiara", "Dara", "Elif", "Emeka", "Esme",
    "Farid", "Femke", "Gael", "Hana", "Ines", "Ivo", "Jonas", "Kaito", "Kemi", "Lars", "Lea", "Lior", "Mara",
    "Mateo", "Mei", "Nadia", "Nico", "Noor", "Oren", "Pia", "Quinn", "Rafa", "Ravi", "Rosa", "Sami", "Sena",
    "Soren", "Tala", "Teo", "Una", "Vera", "Wim", "Yara", "Yuki", "Zane", "Zoe", "Ilse",
]

CATEGORIES = {  # category: (subcategories, net price range in EUR)
    "Tents": (["Backpacking tents", "Family tents", "Shelters"], (70, 390)),
    "Sleeping bags": (["Down bags", "Synthetic bags", "Sleeping pads"], (25, 240)),
    "Backpacks": (["Daypacks", "Trekking packs", "Hydration packs"], (22, 190)),
    "Footwear": (["Hiking boots", "Trail shoes", "Sandals"], (35, 160)),
    "Clothing": (["Jackets", "Base layers", "Trousers"], (15, 220)),
    "Cooking": (["Stoves", "Cookware", "Water filters"], (8, 110)),
    "Lighting": (["Headlamps", "Lanterns"], (10, 70)),
    "Navigation": (["GPS units", "Compasses", "Maps"], (6, 290)),
}
NAME_WORDS = ["Ridge", "Cirrus", "Fjord", "Alder", "Basalt", "Summit", "Larch", "Tundra", "Cobalt", "Ember",
              "Granite", "Juniper", "Kestrel", "Lumen", "Moraine", "Nimbus", "Orca", "Pika", "Quartz", "Scree"]

ORDER_CHANNELS = ["web", "app", "marketplace", None]
ORDER_CHANNEL_WEIGHTS = [55, 26, 14, 5]
SESSION_CHANNELS = ["organic_search", "paid_search", "email", "social", "direct", None]
SESSION_CHANNEL_WEIGHTS = [30, 22, 10, 14, 19, 5]
CAMPAIGNS = {  # spend channel: campaign names
    "paid_search": ["search-brand", "search-generic"],
    "social": ["social-trail-season", "social-winter-camp"],
    "email": ["email-newsletter"],
    "display": ["display-retargeting"],
}
REFUND_REASONS = ["changed_mind", "wrong_size", "damaged", "late_delivery", "other"]
REFUND_REASON_WEIGHTS = [34, 28, 18, 12, 8]

CENT = Decimal("0.01")


def money(value) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def cumulative(weights: list[float]) -> list[float]:
    total, out = 0.0, []
    for w in weights:
        total += w
        out.append(total)
    return out


def stream(table: str) -> random.Random:
    """The random stream for one table: seeded by the shop's seed and the table's name."""
    return random.Random(f"{SHOP_SEED}:{table}")


def loaded_at(day: date) -> datetime:
    """When the nightly load brought in a row for an event on `day`: 02:00 UTC the next day."""
    return datetime.combine(day + timedelta(days=1), time(2, 0))


def days(first: date, last: date) -> list[date]:
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


@dataclass
class Table:
    """A generated table: its column names and types (DuckDB SQL) and its rows as column lists."""
    name: str
    columns: dict[str, str]
    data: dict[str, list] = field(default_factory=dict)

    def __post_init__(self):
        self.data = {c: [] for c in self.columns}

    def add(self, **row):
        for c in self.columns:
            self.data[c].append(row[c])

    def __len__(self):
        return len(next(iter(self.data.values())))


def day_weight(day: date) -> float:
    """Relative order volume on a day: growth over the period, a summer camping season and a December peak."""
    growth = 1 + 0.6 * (day - FIRST_DAY).days / (LAST_DAY - FIRST_DAY).days
    season = {5: 1.25, 6: 1.35, 7: 1.3, 8: 1.15, 11: 1.2, 12: 1.45, 1: 0.8, 2: 0.75}.get(day.month, 1.0)
    weekend = 1.1 if day.weekday() >= 5 else 1.0
    return growth * season * weekend


def generate_products(rng: random.Random) -> Table:
    t = Table("products", {"product_id": "INTEGER", "product_name": "VARCHAR", "category": "VARCHAR",
                           "subcategory": "VARCHAR", "list_price_eur": "DECIMAL(10,2)", "unit_cost": "DECIMAL(10,2)",
                           "launched_on": "DATE", "discontinued_on": "DATE", "_loaded_at": "TIMESTAMP"})
    product_id = 2001
    for category, (subcategories, (low, high)) in CATEGORIES.items():
        for i in range(15):
            subcategory = subcategories[i % len(subcategories)]
            net = money(rng.uniform(low, high))
            if rng.random() < 0.8:
                launched = FIRST_DAY - timedelta(days=rng.randint(30, 900))
            else:
                launched = FIRST_DAY + timedelta(days=rng.randint(30, 760))
            discontinued = None
            if rng.random() < 0.1:
                discontinued = max(launched, FIRST_DAY) + timedelta(days=rng.randint(120, 500))
                discontinued = discontinued if discontinued < LAST_DAY else None
            noun = subcategory.split()[-1].rstrip("s").lower()
            t.add(product_id=product_id, product_name=f"{rng.choice(NAME_WORDS)} {rng.randint(1, 9)}0 {noun}",
                  category=category, subcategory=subcategory, list_price_eur=net,
                  unit_cost=money(net * Decimal(str(round(rng.uniform(0.38, 0.55), 2)))),
                  launched_on=launched, discontinued_on=discontinued, _loaded_at=loaded_at(max(launched, FIRST_DAY)))
            product_id += 1
    return t


def generate_customers(rng: random.Random) -> Table:
    """3,040 real customers, 6 test accounts and 54 duplicates whose email differs only in case."""
    t = Table("customers", {"customer_id": "INTEGER", "customer_name": "VARCHAR", "email": "VARCHAR",
                            "phone_last2": "VARCHAR", "country": "VARCHAR", "region": "VARCHAR",
                            "signed_up_at": "TIMESTAMP", "_loaded_at": "TIMESTAMP"})
    countries, weights = list(COUNTRY_WEIGHTS), list(COUNTRY_WEIGHTS.values())
    rows = []
    for n in range(1, 3041):
        country = rng.choices(countries, weights)[0]
        # Most customers sign up before or during the period; earlier sign-ups are more common.
        signed = datetime.combine(FIRST_DAY, time()) + timedelta(days=rng.triangular(-500, 870, -100),
                                                                 seconds=rng.randint(0, 86399))
        rows.append(dict(customer_name=f"{rng.choice(GIVEN_NAMES)} {rng.choice('ABCDEFGHJKLMNOPRSTVW')}.",
                         email=f"customer-{n:05d}@example.com", phone_last2=f"{rng.randint(0, 99):02d}",
                         country=country, region=COUNTRIES[country][0], signed_up_at=signed.replace(microsecond=0)))
    for n in range(1, 7):
        rows.append(dict(customer_name=f"Test {chr(64 + n)}.", email=f"qa-{n:02d}@test.example.com",
                         phone_last2="00", country=["DE", "US", "AU", "GB", "FR", "CA"][n - 1],
                         region=COUNTRIES[["DE", "US", "AU", "GB", "FR", "CA"][n - 1]][0],
                         signed_up_at=datetime(2024, 1, 15, 9, 0) + timedelta(days=30 * n)))
    for original in rng.sample(range(3040), 54):
        o = rows[original]
        local, domain = o["email"].split("@")
        email = rng.choice([local.capitalize() + "@" + domain, o["email"].upper(), local + "@Example.com"])
        rows.append(dict(o, email=email, signed_up_at=o["signed_up_at"] + timedelta(days=rng.randint(20, 400))))
    rows.sort(key=lambda r: r["signed_up_at"])
    for customer_id, row in enumerate(rows, start=1):
        t.add(customer_id=customer_id, _loaded_at=loaded_at(max(row["signed_up_at"].date(), FIRST_DAY)), **row)
    return t


def price_in(currency: str, net_eur: Decimal, tax_rate: Decimal) -> Decimal:
    """The shop's shelf price: EMEA prices include VAT and end in .95; USD prices exclude sales tax and end in .99."""
    if currency == "EUR":
        return Decimal(round(net_eur * Decimal("1.2"))) - Decimal("0.05")
    if currency == "GBP":
        return Decimal(round(net_eur * Decimal("0.86") * Decimal("1.2"))) - Decimal("0.05")
    return Decimal(round(net_eur * Decimal("1.08"))) - Decimal("0.01")


def generate_orders(rng: random.Random, customers: Table) -> Table:
    t = Table("orders", {"order_id": "INTEGER", "customer_id": "INTEGER", "placed_at": "TIMESTAMP",
                         "status": "VARCHAR", "currency": "VARCHAR", "channel": "VARCHAR", "is_test": "BOOLEAN",
                         "_loaded_at": "TIMESTAMP"})
    c = customers.data
    real = [i for i, e in enumerate(c["email"]) if not e.endswith("@test.example.com")]
    tests = [i for i, e in enumerate(c["email"]) if e.endswith("@test.example.com")]
    signed = [c["signed_up_at"][i] for i in real]            # already sorted by sign-up
    activity = [rng.paretovariate(1.6) for _ in real]
    cumulative = [0.0]
    for a in activity:
        cumulative.append(cumulative[-1] + a)
    period = days(FIRST_DAY, LAST_DAY)
    order_days = sorted(rng.choices(period, [day_weight(d) for d in period], k=15000))
    orders = []
    for day in order_days:
        is_test = rng.random() < 0.01
        if is_test:
            index = rng.choice(tests)
        else:
            eligible = bisect.bisect_right(signed, datetime.combine(day, time(23, 59)))
            eligible = max(eligible, 1)
            index = real[bisect.bisect_right(cumulative, rng.random() * cumulative[eligible]) - 1]
        country = c["country"][index]
        region, currency = COUNTRIES[country][0], COUNTRIES[country][1]
        local_hour = rng.choices(range(24), [1, 1, 1, 1, 1, 1, 2, 3, 4, 5, 5, 5, 6, 6, 5, 5, 5, 6, 7, 9, 10, 9, 6, 3])[0]
        placed = (datetime.combine(day, time(local_hour)) + timedelta(hours=REGION_UTC_OFFSET[region],
                                                                     seconds=rng.randint(0, 3599)))
        age = (LAST_DAY - day).days
        if age < 3:
            status = rng.choice(["placed", "placed", "shipped"])
        elif age < 8:
            status = rng.choice(["shipped", "shipped", "delivered", "cancelled"])
        else:
            status = rng.choices(["delivered", "cancelled", "returned"], [88.5, 5, 6.5])[0]
        channel = rng.choices(ORDER_CHANNELS, ORDER_CHANNEL_WEIGHTS)[0]
        orders.append((placed, c["customer_id"][index], status, currency, channel, is_test))
    orders.sort(key=lambda o: o[0])
    for order_id, (placed, customer_id, status, currency, channel, is_test) in enumerate(orders, start=100001):
        t.add(order_id=order_id, customer_id=customer_id, placed_at=placed, status=status, currency=currency,
              channel=channel, is_test=is_test, _loaded_at=loaded_at(placed.date()))
    return t


def generate_order_lines(rng: random.Random, orders: Table, customers: Table, products: Table) -> Table:
    t = Table("order_lines", {"order_id": "INTEGER", "line_number": "INTEGER", "product_id": "INTEGER",
                              "quantity": "INTEGER", "unit_price": "DECIMAL(10,2)", "discount": "DECIMAL(10,2)",
                              "tax": "DECIMAL(10,2)", "_loaded_at": "TIMESTAMP"})
    country_of = dict(zip(customers.data["customer_id"], customers.data["country"]))
    p = products.data
    # Cheaper products sell more often, and a few products sell far more than the rest.
    popularity = [rng.paretovariate(1.2) / float(price) ** 0.5 for price in p["list_price_eur"]]
    catalog: dict[date, tuple[list[int], list[float]]] = {}      # products on sale on a day, with cumulative weights
    line_counts, line_weights = [1, 2, 3, 4, 5, 6], cumulative([30, 27, 19, 12, 8, 4])
    quantities, quantity_weights = [1, 2, 3, 4], cumulative([76, 17, 5, 2])
    o = orders.data
    for k, order_id in enumerate(o["order_id"]):
        day = o["placed_at"][k].date()
        _, currency, rate, included = COUNTRIES[country_of[o["customer_id"][k]]]
        rate = Decimal(rate)
        if day not in catalog:
            on_sale = [i for i in range(len(p["product_id"])) if p["launched_on"][i] <= day
                       and (p["discontinued_on"][i] is None or p["discontinued_on"][i] > day)]
            catalog[day] = on_sale, cumulative([popularity[i] for i in on_sale])
        on_sale, weights = catalog[day]
        count = rng.choices(line_counts, cum_weights=line_weights)[0]
        picked = []
        while len(picked) < count:
            i = rng.choices(on_sale, cum_weights=weights)[0]
            if i not in picked:
                picked.append(i)
        for line_number, i in enumerate(picked, start=1):
            quantity = rng.choices(quantities, cum_weights=quantity_weights)[0]
            unit_price = price_in(currency, p["list_price_eur"][i], rate)
            discount = Decimal(0)
            if rng.random() < 0.18:
                discount = -money(quantity * unit_price * Decimal(rng.choice(["0.10", "0.15", "0.20"])))
            amount = quantity * unit_price + discount
            tax = money(amount * rate / (1 + rate)) if included else money(amount * rate)
            t.add(order_id=order_id, line_number=line_number, product_id=p["product_id"][i], quantity=quantity,
                  unit_price=unit_price, discount=discount, tax=tax, _loaded_at=o["_loaded_at"][k])
    return t


def generate_refunds(rng: random.Random, orders: Table, lines: Table, customers: Table) -> Table:
    """Full refunds for returned orders and partial ones for some delivered orders, often in a later month."""
    t = Table("refunds", {"refund_id": "INTEGER", "order_id": "INTEGER", "amount": "DECIMAL(10,2)",
                          "currency": "VARCHAR", "reason": "VARCHAR", "refunded_at": "TIMESTAMP",
                          "_loaded_at": "TIMESTAMP"})
    country_of = dict(zip(customers.data["customer_id"], customers.data["country"]))
    paid: dict[int, list[Decimal]] = {}
    for order_id, quantity, price, discount, tax in zip(*(lines.data[c] for c in
                                                          ("order_id", "quantity", "unit_price", "discount", "tax"))):
        paid.setdefault(order_id, []).append((quantity, price, discount, tax))
    refunds = []
    o = orders.data
    for k, order_id in enumerate(o["order_id"]):
        status, placed = o["status"][k], o["placed_at"][k]
        included = COUNTRIES[country_of[o["customer_id"][k]]][3]

        def charged(line):
            quantity, price, discount, tax = line
            return quantity * price + discount + (0 if included else tax)

        if status == "returned":
            amount, reason = sum(charged(line) for line in paid[order_id]), None
        elif status == "delivered" and rng.random() < 0.012:
            amount, reason = charged(rng.choice(paid[order_id])), rng.choice(["damaged", "late_delivery", "other"])
        else:
            continue
        refunded = placed + timedelta(days=rng.randint(6, 48), seconds=rng.randint(0, 86399))
        if refunded.date() > REFUNDS_LOADED_THROUGH:
            continue                                         # not loaded yet: the refunds feed stopped
        reason = reason or rng.choices(REFUND_REASONS, REFUND_REASON_WEIGHTS)[0]
        refunds.append((refunded, order_id, money(amount), o["currency"][k], reason))
    refunds.sort()
    for refund_id, (refunded, order_id, amount, currency, reason) in enumerate(refunds, start=500001):
        t.add(refund_id=refund_id, order_id=order_id, amount=amount, currency=currency, reason=reason,
              refunded_at=refunded, _loaded_at=loaded_at(refunded.date()))
    return t


def generate_sessions(rng: random.Random, orders: Table) -> Table:
    """Visits to the shop: one converting session for most web orders, the rest browsing; many anonymous."""
    t = Table("sessions", {"session_id": "INTEGER", "customer_id": "INTEGER", "started_at": "TIMESTAMP",
                           "channel": "VARCHAR", "campaign": "VARCHAR", "converted_order_id": "INTEGER",
                           "_loaded_at": "TIMESTAMP"})
    o = orders.data
    sessions = []

    channel_weights = cumulative(SESSION_CHANNEL_WEIGHTS)

    def pick_channel():
        channel = rng.choices(SESSION_CHANNELS, cum_weights=channel_weights)[0]
        campaign = rng.choice(CAMPAIGNS[channel]) if channel in CAMPAIGNS else None
        return channel, campaign

    for k, order_id in enumerate(o["order_id"]):
        if o["channel"][k] == "web" and rng.random() < 0.9:
            channel, campaign = pick_channel()
            started = o["placed_at"][k] - timedelta(seconds=rng.randint(120, 2400))
            sessions.append((started, o["customer_id"][k], channel, campaign, order_id))
    period = days(FIRST_DAY, LAST_DAY)
    customer_ids = sorted(set(o["customer_id"]))
    browsing_days = rng.choices(period, [day_weight(d) for d in period], k=60000 - len(sessions))
    for day in browsing_days:
        channel, campaign = pick_channel()
        customer = rng.choice(customer_ids) if rng.random() < 0.4 else None
        started = datetime.combine(day, time()) + timedelta(seconds=rng.randint(0, 86399))
        sessions.append((started, customer, channel, campaign, None))
    sessions.sort(key=lambda s: s[0])
    for session_id, (started, customer, channel, campaign, converted) in enumerate(sessions, start=1):
        t.add(session_id=session_id, customer_id=customer, started_at=started, channel=channel, campaign=campaign,
              converted_order_id=converted, _loaded_at=loaded_at(started.date()))
    return t


def generate_marketing_spend(rng: random.Random) -> Table:
    t = Table("marketing_spend", {"spend_date": "DATE", "channel": "VARCHAR", "campaign": "VARCHAR",
                                  "region": "VARCHAR", "amount_eur": "DECIMAL(10,2)", "_loaded_at": "TIMESTAMP"})
    pairs = [(channel, campaign) for channel, names in CAMPAIGNS.items() for campaign in names]
    for day in days(FIRST_DAY, LAST_DAY):
        for region in ("EMEA", "AMER", "APAC"):
            channel, campaign = pairs[(day.toordinal() + len(region)) % len(pairs)]
            amount = money(rng.uniform(60, 420) * day_weight(day) * {"EMEA": 1.0, "AMER": 1.1, "APAC": 0.5}[region])
            t.add(spend_date=day, channel=channel, campaign=campaign, region=region, amount_eur=amount,
                  _loaded_at=loaded_at(day))
    return t


def generate_fx_rates(rng: random.Random) -> Table:
    """Daily rates to EUR. Generated by a random walk, not real rates."""
    t = Table("fx_rates", {"rate_date": "DATE", "currency": "VARCHAR", "eur_per_unit": "DECIMAL(10,6)",
                           "_loaded_at": "TIMESTAMP"})
    level = {"GBP": 1.17, "USD": 0.92}
    # One day either side of the period: an order's UTC day can fall outside its local one.
    for day in days(FIRST_DAY - timedelta(days=1), LAST_DAY + timedelta(days=1)):
        t.add(rate_date=day, currency="EUR", eur_per_unit=Decimal("1.000000"), _loaded_at=loaded_at(day))
        for currency in ("GBP", "USD"):
            level[currency] *= 1 + rng.gauss(0, 0.003)
            t.add(rate_date=day, currency=currency, eur_per_unit=Decimal(f"{level[currency]:.6f}"),
                  _loaded_at=loaded_at(day))
    return t


def generate_shop() -> dict[str, Table]:
    """Every raw table of the shop, by name, in load order."""
    products = generate_products(stream("products"))
    customers = generate_customers(stream("customers"))
    orders = generate_orders(stream("orders"), customers)
    lines = generate_order_lines(stream("order_lines"), orders, customers, products)
    refunds = generate_refunds(stream("refunds"), orders, lines, customers)
    sessions = generate_sessions(stream("sessions"), orders)
    tables = [products, customers, orders, lines, refunds, sessions,
              generate_marketing_spend(stream("marketing_spend")), generate_fx_rates(stream("fx_rates"))]
    return {t.name: t for t in tables}
