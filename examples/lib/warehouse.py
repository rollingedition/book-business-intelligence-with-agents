"""The shop's warehouse: a DuckDB database with a `raw` schema, as loaded, and an `analytics` schema of marts.

`connect()` generates the shop (`lib/shop_data.py`), loads the raw tables, builds the marts in SQL, as an analytics
engineer would, and returns a read-only connection. It takes a few seconds, and no generated rows are committed.

DuckDB can't open an in-memory database read-only, so the warehouse is written to a temporary file that is deleted
when the program exits, and reopened read-only with file access off (no reading other files, no attaching
databases) and its settings locked, so a query can't switch those protections back on.

`describe_schema()` lists every table and column: the schema an agent sees when it is given nothing else.

From chapter 5, a third schema, `semantic`, holds three views over the marts that the semantic layer reads.

From chapter 7, `agent_warehouse()` gives the agent's SQL a database of its own: a second file that holds copies of
the allowed marts and nothing else, opened read-only with the same protections and more (`AGENT_SETTINGS`). Given a
role's policy, it holds that role's views of the marts instead: the database every query of that role runs on.

From chapter 11, `agent_warehouse(con, policy=..., semantic=SEMANTIC_TABLES)` also copies the semantic layer's
views and calendar, as the role sees them, so the semantic layer can run on a role's database too.
"""
from __future__ import annotations

import atexit
import shutil
import tempfile
from pathlib import Path

import duckdb

from .shop_data import generate_shop

REGION_TIME_ZONES = {"EMEA": "Europe/Berlin", "AMER": "America/New_York", "APAC": "Asia/Singapore"}

MARTS = """
CREATE SCHEMA analytics;

CREATE TABLE analytics.dim_date AS
SELECT d::DATE AS date_day,
       year(d) AS calendar_year,
       month(d) AS calendar_month,
       CASE WHEN month(d) >= 2 THEN year(d) + 1 ELSE year(d) END AS fiscal_year,
       (month(d) + 10) % 12 // 3 + 1 AS fiscal_quarter,
       (month(d) + 10) % 12 + 1 AS fiscal_month,
       dayname(d) AS day_name
FROM range(DATE '2024-02-01', DATE '2026-08-01', INTERVAL 1 DAY) AS days(d);

CREATE TABLE analytics.region_time_zones (region VARCHAR, time_zone VARCHAR);
INSERT INTO analytics.region_time_zones VALUES {zones};

-- Duplicate customers differ only in their email's case: the first sign-up keeps its ID, the others map to it.
CREATE TABLE analytics.customer_id_map AS
SELECT customer_id,
       first_value(customer_id) OVER (PARTITION BY lower(email) ORDER BY signed_up_at, customer_id) AS canonical_id
FROM raw.customers;

CREATE TABLE analytics.fct_orders AS
WITH lines AS (
    SELECT order_id, count(*) AS line_count, sum(quantity * unit_price + discount) AS line_total,
           sum(discount) AS discount, sum(tax) AS tax
    FROM raw.order_lines GROUP BY order_id
), orders AS (
    SELECT o.*, c.country, c.region, m.canonical_id, z.time_zone, l.line_count, l.line_total, l.discount, l.tax,
           r.eur_per_unit
    FROM raw.orders AS o
    JOIN raw.customers AS c USING (customer_id)
    JOIN analytics.customer_id_map AS m USING (customer_id)
    JOIN analytics.region_time_zones AS z ON z.region = c.region
    JOIN lines AS l USING (order_id)
    JOIN raw.fx_rates AS r ON r.rate_date = o.placed_at::DATE AND r.currency = o.currency
    WHERE NOT o.is_test
)
SELECT order_id,
       canonical_id AS customer_id,
       region,
       country,
       coalesce(channel, '(none)') AS channel,
       status,
       placed_at,
       timezone(time_zone, placed_at AT TIME ZONE 'UTC')::DATE AS order_date_local,
       currency,
       line_count,
       -- EMEA prices include VAT; AMER and APAC add sales tax on top.
       round((line_total + CASE WHEN region = 'EMEA' THEN 0 ELSE tax END) * eur_per_unit, 2)::DECIMAL(12,2)
           AS gross_revenue_eur,
       round((line_total - CASE WHEN region = 'EMEA' THEN tax ELSE 0 END) * eur_per_unit, 2)::DECIMAL(12,2)
           AS net_revenue_eur,
       round(-discount * eur_per_unit, 2)::DECIMAL(12,2) AS discount_eur,
       round(tax * eur_per_unit, 2)::DECIMAL(12,2) AS tax_eur,
       _loaded_at
FROM orders;

CREATE TABLE analytics.fct_order_lines AS
SELECT l.order_id, l.line_number, l.product_id, l.quantity,
       round(l.unit_price * r.eur_per_unit, 2)::DECIMAL(12,2) AS unit_price_eur,
       round(-l.discount * r.eur_per_unit, 2)::DECIMAL(12,2) AS discount_eur,
       round(l.tax * r.eur_per_unit, 2)::DECIMAL(12,2) AS tax_eur,
       round((l.quantity * l.unit_price + l.discount - CASE WHEN f.region = 'EMEA' THEN l.tax ELSE 0 END)
             * r.eur_per_unit, 2)::DECIMAL(12,2) AS net_amount_eur,
       l._loaded_at
FROM raw.order_lines AS l
JOIN analytics.fct_orders AS f USING (order_id)
JOIN raw.fx_rates AS r ON r.rate_date = f.placed_at::DATE AND r.currency = f.currency;

CREATE TABLE analytics.fct_refunds AS
SELECT x.refund_id, x.order_id, f.customer_id, f.region, x.reason, x.refunded_at,
       round(x.amount * r.eur_per_unit, 2)::DECIMAL(12,2) AS amount_eur,
       date_trunc('month', timezone(z.time_zone, x.refunded_at AT TIME ZONE 'UTC'))::DATE AS refund_month,
       date_trunc('month', f.order_date_local)::DATE AS order_month,
       x._loaded_at
FROM raw.refunds AS x
JOIN analytics.fct_orders AS f USING (order_id)
JOIN analytics.region_time_zones AS z ON z.region = f.region
JOIN raw.fx_rates AS r ON r.rate_date = x.refunded_at::DATE AND r.currency = x.currency;

CREATE TABLE analytics.dim_customers AS
SELECT c.customer_id, c.customer_name, lower(c.email) AS email, c.phone_last2, c.country, c.region,
       c.signed_up_at, min(f.order_date_local) AS first_order_on, c._loaded_at
FROM raw.customers AS c
JOIN analytics.customer_id_map AS m ON m.customer_id = c.customer_id AND m.canonical_id = c.customer_id
LEFT JOIN analytics.fct_orders AS f ON f.customer_id = c.customer_id
WHERE c.email NOT LIKE '%@test.example.com'
GROUP BY ALL;

CREATE TABLE analytics.dim_products AS
SELECT product_id, product_name, category, subcategory, unit_cost, launched_on, discontinued_on, _loaded_at
FROM raw.products;

CREATE TABLE analytics.fct_sessions AS
SELECT s.session_id, m.canonical_id AS customer_id, s.started_at, coalesce(s.channel, '(none)') AS channel,
       s.campaign, s.converted_order_id, s._loaded_at
FROM raw.sessions AS s
LEFT JOIN analytics.customer_id_map AS m USING (customer_id);

-- An older mart, kept because old dashboards read it: revenue here is gross, tax included, test orders kept.
CREATE TABLE analytics.orders_legacy AS
SELECT o.order_id AS id, o.customer_id AS cust_id, o.placed_at::DATE AS order_date, o.status AS order_status,
       c.region AS sales_region,
       round((l.line_total + CASE WHEN c.region = 'EMEA' THEN 0 ELSE l.tax END) * r.eur_per_unit, 2)::DECIMAL(12,2)
           AS revenue
FROM raw.orders AS o
JOIN raw.customers AS c USING (customer_id)
JOIN (SELECT order_id, sum(quantity * unit_price + discount) AS line_total, sum(tax) AS tax
      FROM raw.order_lines GROUP BY order_id) AS l USING (order_id)
JOIN raw.fx_rates AS r ON r.rate_date = o.placed_at::DATE AND r.currency = o.currency;

DROP TABLE analytics.customer_id_map;
"""

# Chapter 5: three views the semantic layer reads, in their own schema so `describe_schema()` and `table_sizes()`,
# which list `raw` and `analytics`, are unchanged. MetricFlow needs every fact to carry its own date, and a time spine
# whose custom grains name one period each: lines get their order's local day, refunds get their own local day and
# their order's, and the calendar labels each fiscal quarter with its year.
SEMANTIC_VIEWS = """
CREATE SCHEMA semantic;

CREATE VIEW semantic.calendar AS
SELECT date_day, fiscal_year, fiscal_year || '-Q' || fiscal_quarter AS fiscal_quarter
FROM analytics.dim_date;

CREATE VIEW semantic.order_lines AS
SELECT l.*, o.order_date_local
FROM analytics.fct_order_lines AS l
JOIN analytics.fct_orders AS o USING (order_id);

CREATE VIEW semantic.refunds AS
SELECT r.*, timezone(CASE r.region {zones} END, r.refunded_at AT TIME ZONE 'UTC')::DATE AS refund_date_local,
       o.order_date_local
FROM analytics.fct_refunds AS r
JOIN analytics.fct_orders AS o USING (order_id);
"""

READ_ONLY_SETTINGS = {
    "enable_external_access": False,   # no reading or writing other files, no ATTACH, no installing extensions
    "autoload_known_extensions": False,     # loading extensions is a separate setting: no loading one a query needs,
    "autoinstall_known_extensions": False,  # no installing it,
    "allow_community_extensions": False,    # and none from the community repository
    "memory_limit": "1GB",
    "threads": 2,
    "lock_configuration": True,        # SET can't change any of the above
}

# Chapter 7: the agent's database. The marts its SQL may read, named one by one, so a mart added later isn't
# allowed until someone adds it here. analytics.orders_legacy, the old revenue definition, is left out.
AGENT_TABLES = ("dim_customers", "dim_date", "dim_products", "fct_order_lines", "fct_orders", "fct_refunds",
                "fct_sessions")
# Chapter 11: what the semantic layer reads besides the marts, for a role's database that serves metrics.
SEMANTIC_TABLES = ("calendar", "order_lines", "refunds")
AGENT_SETTINGS = READ_ONLY_SETTINGS | {
    "allow_persistent_secrets": False,       # no stored credentials to read
    # Constant folding runs while DuckDB plans a query, where interrupt() isn't checked, so a constant expression
    # that takes a minute to fold would outlast an interrupt. Turned off, it is computed while the query runs. The
    # guard kills its worker process at the deadline instead, so this is a second line, not the only one.
    "disabled_optimizers": "expression_rewriter",
    # Named again, though READ_ONLY_SETTINGS sets them, because the agent's queries rely on them: DuckDB stops a query
    # that needs more memory than this with an Out of Memory error, and runs each on at most two threads. The guard's
    # worker process opens the database with these same settings.
    "memory_limit": "1GB",
    "threads": 2,
}


def build(path: Path) -> None:
    """Generate the shop and write its warehouse to a DuckDB file at `path`."""
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE SCHEMA raw")
        for name, table in generate_shop().items():
            columns = ", ".join(f"{c} {t}" for c, t in table.columns.items())
            con.execute(f"CREATE TABLE raw.{name} ({columns})")
            values = ", ".join(f"unnest(${i + 1})::{t}" for i, t in enumerate(table.columns.values()))
            # Dates, timestamps and decimals travel as text, which DuckDB casts faster than Python objects.
            data = [[None if v is None else str(v) for v in column] if t.startswith(("DATE", "TIMESTAMP", "DECIMAL"))
                    else column for column, t in zip(table.data.values(), table.columns.values())]
            con.execute(f"INSERT INTO raw.{name} SELECT {values}", data)
        zones = ", ".join(f"('{r}', '{z}')" for r, z in REGION_TIME_ZONES.items())
        con.execute(MARTS.format(zones=zones))
        con.execute("DROP TABLE analytics.region_time_zones")
        cases = " ".join(f"WHEN '{r}' THEN '{z}'" for r, z in REGION_TIME_ZONES.items())
        con.execute(SEMANTIC_VIEWS.format(zones=cases))


def connect() -> duckdb.DuckDBPyConnection:
    """Build the shop's warehouse and return a read-only connection to it."""
    folder = Path(tempfile.mkdtemp(prefix="shop-"))
    atexit.register(shutil.rmtree, folder, ignore_errors=True)
    path = folder / "shop.duckdb"
    build(path)
    return duckdb.connect(str(path), read_only=True, config=READ_ONLY_SETTINGS)


def agent_warehouse(con: duckdb.DuckDBPyConnection, tables: tuple[str, ...] = AGENT_TABLES,
                    schema: str = "analytics", policy=None, semantic: tuple[str, ...] = ()
                    ) -> duckdb.DuckDBPyConnection:
    """A read-only connection to a new database that holds a copy of each of `tables` from the warehouse behind `con`.

    Nothing else is in it: no `raw` schema, no legacy mart, no semantic views. With file access off it can't attach
    the shop's file either, so a query the guard misjudges can read only these tables and DuckDB's own catalog.

    Given a role's `policy` (chapter 9's `policies.Policy`), it is that role's database: each table is the role's view
    of the mart, the rows its filter keeps, with masked columns holding the mask and denied columns left out, and a
    table the role may not read isn't there. DuckDB has no roles or GRANT, and a view can be read only by a
    connection that can read the tables under it, so each view's result is written as a table of the same name. The
    database is the boundary: whatever SQL reaches it, the role's rows and columns are all there is to read.

    `semantic` names views of the `semantic` schema to copy the same way, such as `SEMANTIC_TABLES`, the views and
    calendar the semantic layer reads besides the marts. By default there are none.
    """
    (source,), = con.execute("SELECT path FROM duckdb_databases() WHERE database_name = current_database()").fetchall()
    folder = Path(tempfile.mkdtemp(prefix="agent-"))
    atexit.register(shutil.rmtree, folder, ignore_errors=True)
    path = folder / "agent.duckdb"
    with duckdb.connect(str(path)) as writer:
        writer.execute(f"ATTACH '{source}' AS shop (READ_ONLY)")
        writer.execute(f"CREATE SCHEMA {schema}")
        writer.execute("USE shop")       # names in a row filter's subquery read the shop's marts, as in chapter 9
        for table, view in _role_views(con, tables, schema, policy):
            writer.execute(f"CREATE TABLE agent.{schema}.{table} AS {view}")
        if semantic:
            writer.execute("CREATE SCHEMA agent.semantic")
            for table, view in _role_views(con, semantic, "semantic", policy):
                writer.execute(f"CREATE TABLE agent.semantic.{table} AS {view}")
    # Persistent secrets are off; the folder is set anyway, so the settings don't name one in the home folder.
    return duckdb.connect(str(path), read_only=True, config=AGENT_SETTINGS | {"secret_directory": str(folder)})


def _role_views(con: duckdb.DuckDBPyConnection, tables: tuple[str, ...], schema: str, policy) -> list[tuple[str, str]]:
    """(table, SELECT) for each table the agent's database holds: the whole mart, or the role's view of it."""
    if policy is None:
        return [(table, f"FROM shop.{schema}.{table}") for table in tables]
    views = []
    for table in tables:
        name = f"{schema}.{table}"
        try:
            policy.check_table(name)
        except Exception:                # PolicyError: the role may not read it, so the table isn't there
            continue
        columns = [c for (c,) in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = ? AND table_name = ? "
            "ORDER BY ordinal_position", [schema, table]).fetchall()]
        views.append((table, policy.subquery(name, columns).sql(dialect="duckdb")))
    return views


def describe_schema(con: duckdb.DuckDBPyConnection, schemas: tuple[str, ...] = ("raw", "analytics")) -> str:
    """Every table in `schemas` with its columns and types, one table per line, as CREATE TABLE statements."""
    rows = con.execute(
        """SELECT table_schema, table_name, string_agg(column_name || ' ' || data_type, ', ' ORDER BY ordinal_position)
           FROM information_schema.columns
           WHERE table_schema IN (SELECT unnest($1::VARCHAR[]))
           GROUP BY ALL ORDER BY table_schema DESC, table_name""", [list(schemas)]).fetchall()
    return "\n".join(f"CREATE TABLE {schema}.{table} ({columns});" for schema, table, columns in rows)


def table_sizes(con: duckdb.DuckDBPyConnection) -> list[tuple[str, int]]:
    """Each table's qualified name and row count, raw first, in name order."""
    tables = con.execute("""SELECT table_schema || '.' || table_name FROM information_schema.tables
                            WHERE table_schema IN ('raw', 'analytics')
                            ORDER BY table_schema DESC, table_name""").fetchall()
    return [(name, con.execute(f"SELECT count(*) FROM {name}").fetchall()[0][0]) for (name,) in tables]


def data_as_of(con: duckdb.DuckDBPyConnection, table: str) -> str:
    """When the newest row in `table` was loaded, from its `_loaded_at` column, as an ISO timestamp."""
    (value,), = con.execute(f"SELECT max(_loaded_at) FROM {table}").fetchall()
    return value.isoformat(sep=" ")
