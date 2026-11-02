"""The agent's own database: copies of the allowed marts, read-only, with files, extensions and settings locked."""
import duckdb

from lib.warehouse import agent_warehouse, connect

shop = connect()
agent = agent_warehouse(shop)                 # a second file: the seven allowed marts, copied, and nothing else
(shop_tables,), = shop.execute("SELECT count(*) FROM duckdb_tables()").fetchall()
print("tables in the shop's warehouse:", shop_tables)
tables = agent.execute("SELECT schema_name || '.' || table_name FROM duckdb_tables() ORDER BY 1").fetchall()
print("tables in the agent's database:", len(tables))
print("the agent's tables:", ", ".join(name for (name,) in tables))

(source,), = shop.execute("SELECT path FROM duckdb_databases() WHERE database_name = 'shop'").fetchall()
ATTEMPTS = {                                  # sent straight to the agent's database, with no guard in front
    "raw table": "SELECT count(*) FROM raw.customers",
    "legacy mart": "SELECT sum(revenue) FROM analytics.orders_legacy",
    "attach the shop's file": f"ATTACH '{source}' AS shop (READ_ONLY)",
    "read a file": "SELECT * FROM read_csv('data/golden/questions.toml')",
    "load an extension": "LOAD httpfs",
    "turn file access back on": "SET enable_external_access = true",
}
for label, sql in ATTEMPTS.items():
    try:
        agent.execute(sql).fetchall()
        print(f"{label}: allowed")
    except duckdb.Error as e:
        kind, message = str(e).splitlines()[0].split(": ", 1)
        print(f"{label}: {kind}, {message.split(' - ')[-1]}")   # the file's path is left out of the output

# What no setting hides: DuckDB's own catalog, which every database has.
(listed,), = agent.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'analytics'").fetchall()
print("catalog, tables it lists:", listed)
(settings,), = agent.execute("SELECT count(*) FROM duckdb_settings()").fetchall()
print("catalog, settings it lists:", settings)
(paths,), = agent.execute("SELECT count(*) FROM duckdb_databases() WHERE path IS NOT NULL").fetchall()
print("catalog, database files it names:", paths)
