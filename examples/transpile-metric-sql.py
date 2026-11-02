"""Write one compiled metric request in six warehouses' dialects, and show what transpiling doesn't check."""
import sqlglot
from sqlglot import ErrorLevel

from lib.semantic import MetricRequest, load

request = MetricRequest(("refund_rate",), ("metric_time__quarter",), {"metric_time__year": 2025})
compiled = load().compile(request)

for dialect in ("duckdb", "snowflake", "bigquery", "databricks", "postgres", "tsql"):
    sql = compiled.sql(dialect=dialect, pretty=True, unsupported_level=ErrorLevel.RAISE)
    lines = [line.strip().rstrip(",") for line in sql.splitlines()]
    print(f"{dialect} quarter: {next(line for line in lines if 'TRUNC' in line)}")
    print(f"{dialect} ratio: {next(line for line in lines if 'NULLIF' in line)}")

# The compiler casts the column to DATE before truncating. Without the cast, BigQuery gets TIMESTAMP_TRUNC.
uncast = sqlglot.transpile("SELECT DATE_TRUNC('quarter', order_date_local)", read="duckdb", write="bigquery")[0]
print(f"bigquery without the cast: {uncast}")

# Transpiling translates syntax; it doesn't check that the target warehouse has the function.
tsql = sqlglot.transpile("SELECT * FROM customers WHERE country ILIKE 'g%'", read="duckdb", write="tsql",
                         unsupported_level=ErrorLevel.RAISE)[0]
print(f"ILIKE in T-SQL: {tsql}")
