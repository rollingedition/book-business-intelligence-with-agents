"""The guard's worker: a process of its own that runs the agent's checked SQL, so the guard can kill it at a deadline.

`sql_guard.Worker` starts it as `python -I guard_worker.py FD PATH SETTINGS HEADROOM`. It opens the database file at
PATH read-only, with SETTINGS (JSON): the same settings as the guard's connection. DuckDB's `memory_limit` "only
applies to the buffer manager", so the strings and lists an expression builds aren't counted in it; once the database
is open, the worker caps its whole address space at what it holds then plus HEADROOM bytes, and an allocation past
that fails inside DuckDB as an out-of-memory error instead of growing until the system kills the process. It says
it's ready, then answers one request at a time on the pipe whose file descriptor is FD:
- ("explain", sql): the plan, as EXPLAIN (FORMAT json) gives it;
- ("run", sql, max_rows, max_chars): the columns and the rows, fetching at most `max_rows` + 1 rows, or only how
  many characters the result holds if that is more than `max_chars`, so an oversized result never crosses the pipe.
Each request runs on a cursor of its own, closed afterwards. A read-only connection still accepts temporary tables,
views and macros, variables and `search_path`, all held per cursor, so nothing one request creates outlasts it.
A DuckDB error goes back as its class name and message. The worker imports nothing from the book's modules.
"""
import json
import sys
from multiprocessing.connection import Connection

import duckdb


def answer(con: duckdb.DuckDBPyConnection, request: tuple) -> tuple:
    if request[0] == "explain":
        (_, plan), = con.execute(f"EXPLAIN (FORMAT json) {request[1]}").fetchall()
        return ("plan", plan)
    _, sql, max_rows, max_chars = request
    result = con.execute(sql)
    columns = tuple(c[0] for c in result.description)
    rows = result.fetchmany(max_rows + 1)
    if len(rows) > max_rows:
        return ("rows", len(rows))
    size = sum(len(str(value)) for row in rows for value in row)
    if size > max_chars:
        return ("size", size)
    return ("result", columns, rows)


def cap_memory(headroom: int) -> None:
    """Cap the process's address space at its present size plus `headroom` bytes (Linux; elsewhere, no cap)."""
    try:
        import resource
        with open("/proc/self/status") as status:
            size = next(int(line.split()[1]) * 1024 for line in status if line.startswith("VmSize:"))
        _, hard = resource.getrlimit(resource.RLIMIT_AS)  # a cap inherited from outside stays the upper bound
        cap = size + headroom if hard == resource.RLIM_INFINITY else min(size + headroom, hard)
        resource.setrlimit(resource.RLIMIT_AS, (cap, hard))
    except (ImportError, OSError, ValueError, StopIteration):
        pass


def main() -> None:
    pipe = Connection(int(sys.argv[1]))
    con = duckdb.connect(sys.argv[2], read_only=True, config=json.loads(sys.argv[3]))
    con.execute("SELECT 1").fetchall()        # start DuckDB's threads before the cap is measured
    cap_memory(int(sys.argv[4]))
    pipe.send(("ready",))
    while True:
        try:
            request = pipe.recv()
        except EOFError:                      # the guard has gone
            return
        cur = con.cursor()                    # fresh state for each request
        try:
            reply = answer(cur, request)
        except duckdb.Error as e:
            reply = ("error", type(e).__name__, str(e))
        except MemoryError:                   # the cap, reached on the Python side
            reply = ("error", "OutOfMemoryException", "the worker's process ran out of memory")
        finally:
            cur.close()
        pipe.send(reply)


main()
