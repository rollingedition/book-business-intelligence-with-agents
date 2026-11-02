"""Chapter 11: the shop's semantic layer as an MCP server, with the same tools and the same policies as the agent.

`build_server(role, region)` returns an `MCPServer` (the `mcp` SDK's server class) for one role. Its five tools are
chapter 6's metrics-first tools, `list_metrics`, `describe_metric`, `query_metric`, `ask_back` and `cannot_answer`,
and each one calls chapter 9's `PolicyToolbox` for that role, so the server answers exactly as the in-process agent
does. The role is bound when the server is built, never taken from a tool's arguments: no input schema has a `role`
field, and a client that sends one has it dropped by the SDK's argument validation before the tool runs. A server
started over stdio takes its role from the environment (`server_from_environment()`), as the MCP specification asks
of stdio servers; a server on HTTP would take it from a verified access token instead.

The role decides two things. The primary control is the database: `build_server()` derives the role's policy and
opens the role's own read-only database from it, chapter 7's `agent_warehouse(shop, policy=...)` with the semantic
layer's views and calendar, and every tool queries that database and nothing else. It takes the shop's warehouse,
never a connection to query, so a role can't be paired with another role's database. The policy in `PolicyToolbox`
is the second layer behind it. The server reads nothing from the whole warehouse after the copy: `RoleLayer` decides
"forbidden" from the policy alone, so a filter on another region is refused as forbidden rather than answered with no
rows, and a value the role's rows don't hold on any other dimension gets the same correctable error whether it exists
elsewhere or not; the server keeps no connection to the warehouse.

Each tool returns a `ToolReply`: `text`, what the in-process tool shows the model, and `answer`, the `Answer` with its
provenance as structured content, or None when the result doesn't end the run. A request the model could correct,
such as an unknown dimension, is raised as `ToolError`, which the client receives as a result with `is_error` set. A
request the role may not make is not an error: it comes back as an answer that declines, with a reason that starts
"forbidden", because the decision is final and a retry must not reach the rows.

The host side is `ServerToolbox`: it has the `call(name, arguments)` that the book's agent loop (`lib/agent.py`)
expects, and makes each call through an MCP `Client`. `ask_through_server()` runs the loop against a server: it reads
the catalog through `list_metrics`, builds chapter 6's prompt from it, and runs the loop in a worker thread so that
each tool call can go to the server on the event loop. The model, the prompt and the loop are the book's own.
"""
from __future__ import annotations

import os
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import anyio
import anyio.from_thread
import anyio.to_thread
import duckdb
import sqlglot
from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel
from sqlglot import exp

from .agent import Trace, run_agent
from .answers import Answer, Provenance
from .model import Model
from .policies import Policy, PolicyLayer, PolicyToolbox, policy_for
from .prompts import metrics_first_prompt
from .semantic import SemanticLayer, load
from .tools import ToolResult
from .warehouse import SEMANTIC_TABLES, agent_warehouse, connect

SERVER_NAME = "shop-semantic-layer"
READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)
IN_PROCESS_ORDER = ("list_metrics", "describe_metric", "query_metric", "ask_back", "cannot_answer")  # MetricToolbox's
Cell = str | int | float | bool | None
FilterValue = str | int | float | list[str | int | float]


class ProvenanceOut(BaseModel):
    """Where an answer came from: chapter 1's `Provenance`, as JSON."""
    source: str                       # "metric", or "none", "ask_back" for an answer without rows
    metric: str | None
    sql: str                          # the SQL that ran, after the role's policy
    filters: dict[str, Any]           # the request's filters, and "row filter" when the role has one
    role: str
    data_as_of: str | None


class AnswerOut(BaseModel):
    """An answer, as JSON: rows with their provenance, or the reason it can't be given."""
    answered: bool
    columns: list[str]
    rows: list[list[Cell]]
    reason: str | None
    provenance: ProvenanceOut


class ToolReply(BaseModel):
    """What every tool returns: the text the model is shown, and the answer when the result ends the run."""
    text: str
    answer: AnswerOut | None


def _cell(value) -> Cell:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def answer_out(answer: Answer) -> AnswerOut:
    p = answer.provenance
    return AnswerOut(answered=answer.answered, columns=list(answer.columns),
                     rows=[[_cell(v) for v in row] for row in answer.rows], reason=answer.reason,
                     provenance=ProvenanceOut(source=p.source, metric=p.metric, sql=p.sql, filters=p.filters,
                                              role=p.role, data_as_of=p.data_as_of))


def answer_from(structured: dict) -> Answer:
    """The host's side: an `Answer` rebuilt from a tool result's structured content."""
    data = structured["answer"]
    return Answer(columns=tuple(data["columns"]), rows=tuple(tuple(row) for row in data["rows"]),
                  reason=data["reason"], provenance=Provenance(**data["provenance"]))


def _reply(result: ToolResult) -> ToolReply:
    if result.answer is None and result.content.startswith("error:"):
        raise ToolError(result.content)          # the model can correct it: is_error, with the same message
    return ToolReply(text=result.content, answer=answer_out(result.answer) if result.answer else None)


class RoleLayer(PolicyLayer):
    """`PolicyLayer` on the role's own database, deciding "forbidden" from the policy alone.

    A filter on the column a role's row filter tests, such as `region` for a regional lead, is forbidden for every
    value but the role's own. A filter on any other dimension is never forbidden: a value the role's rows don't hold
    gets the toolbox's correctable error, which lists the role's own values, whether other rows hold it or not. So the
    server reads nothing outside the role's database, and a reply can't tell a reader which values exist elsewhere.
    `shop` is accepted for compatibility and not read."""

    def __init__(self, layer: SemanticLayer, policy: Policy, database: duckdb.DuckDBPyConnection,
                 shop: duckdb.DuckDBPyConnection | None = None):
        super().__init__(layer, policy, database)
        self.filter_columns = {table: {eq.this.name for eq in policy.condition(table).find_all(exp.EQ)
                                       if isinstance(eq.this, exp.Column) and eq.expression.is_string
                                       and eq.find_ancestor(exp.Select) is None}     # not in a subquery's filter
                               for table in policy.row_filters} if policy.filtered else {}

    def hidden_values(self, name: str, values: list) -> list:
        parts = name.split("__")
        model = self._owner(parts[-2]) if parts[0] != "metric_time" and len(parts) > 1 else None
        dimension = model.dimensions.get(parts[-1]) if model else None
        if dimension is None or dimension.type != "categorical":
            return []
        column = sqlglot.parse_one(dimension.expr, dialect="duckdb")
        if isinstance(column, exp.Column) and column.name in self.filter_columns.get(model.table, ()):
            return [v for v in values if v != self.policy.region]
        return []


class SemanticServer(MCPServer):
    """An `MCPServer` that keeps the role's database it queries, so a test can check what that database holds."""

    def __init__(self, database: duckdb.DuckDBPyConnection, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.database = database


def build_server(role: str, region: str | None = None, shop: duckdb.DuckDBPyConnection | None = None,
                 layer: SemanticLayer | None = None) -> SemanticServer:
    """The semantic layer as an MCP server for one role, bound here and nowhere else, on that role's own database
    made from the shop's warehouse (`shop`, or a new one)."""
    policy = policy_for(role, region)             # PolicyError for an unknown role, or a lead without a region
    shop = shop or connect()
    database = agent_warehouse(shop, policy=policy, semantic=SEMANTIC_TABLES)
    toolbox = PolicyToolbox(database, RoleLayer(layer or load(), policy, database, shop))
    server = SemanticServer(database, SERVER_NAME, log_level="WARNING", instructions=(
        "The shop's governed metrics. Ask for a metric with query_metric; never write SQL. "
        "Every answer is computed for the role this server was started for, and says so in its provenance."))

    # Registered in name order, so tools/list is the same on every call.
    @server.tool(annotations=READ_ONLY)
    def ask_back(question: str, options: list[str] = []) -> ToolReply:
        """End the run with a question to the person, when the question could mean several metrics or periods.
        List the metrics or readings it could mean in `options`."""
        return _reply(toolbox.ask_back({"question": question, "options": options}))

    @server.tool(annotations=READ_ONLY)
    def cannot_answer(reason: str) -> ToolReply:
        """End the run without an answer, with the reason: the metrics can't answer the question."""
        return _reply(toolbox.cannot_answer({"reason": reason}))

    @server.tool(annotations=READ_ONLY)
    def describe_metric(metric: str) -> ToolReply:
        """One metric's type and definition, the dimensions it can use, and each categorical dimension's values."""
        return _reply(toolbox.describe_metric({"metric": metric}))

    @server.tool(annotations=READ_ONLY)
    def list_metrics() -> ToolReply:
        """Every metric this server's role may query, with its description and the dimensions it can use."""
        return _reply(toolbox.list_metrics({}))

    @server.tool(annotations=READ_ONLY)
    def query_metric(metrics: list[str], group_by: list[str] = [], filters: dict[str, FilterValue] = {},
                     order_by: list[str] = [], limit: int | None = None) -> ToolReply:
        """Compute metrics, grouped by dimensions and filtered by dimension values. Dimension names are as
        list_metrics gives them, such as order__region or metric_time__month. A filter on metric_time takes a year
        as 2025 and a month as "2026-03". Put "-" before a name in order_by to sort descending."""
        return _reply(toolbox.query_metric({"metrics": metrics, "group_by": group_by, "filters": filters,
                                            "order_by": order_by, "limit": limit}))

    return server


def server_from_environment(environ=os.environ, shop: duckdb.DuckDBPyConnection | None = None) -> SemanticServer:
    """A server for the role in `SHOP_ROLE` (and `SHOP_REGION` for a regional lead): how a stdio server, which a
    host launches for one person, receives who that person is. It opens that role's database, as every server does."""
    return build_server(environ["SHOP_ROLE"], environ.get("SHOP_REGION") or None, shop)


async def call(server: MCPServer, tool: str, arguments: dict):
    """One tool call through an in-memory client, with failures outside a tool's body raised as they are."""
    async with Client(server, raise_exceptions=True) as client:
        return await client.call_tool(tool, arguments)


async def run_tests(tests: dict) -> int:
    """Run each `test_` coroutine in `tests`, printing each pass; a failing assertion stops the run."""
    names = [name for name in tests if name.startswith("test_")]
    for name in names:
        await tests[name]()
        print(f"{name}: passed")
    return len(names)


class ServerToolbox:
    """The agent loop's toolbox, with every tool call made through an MCP client. Call it from a worker thread."""

    def __init__(self, client: Client, tools: list[str], role: str = "(the server's)"):
        # The server holds the role. The host's `role` labels only a run that hits the step limit and never
        # reaches the server's provenance.
        self.client, self.tools, self.role = client, tools, role
        self.calls: list[str] = []            # each tool call sent to the server, with whether it was an error

    def call(self, name: str, arguments: dict) -> ToolResult:
        if name not in self.tools:
            return ToolResult(f"error: unknown tool {name!r}; tools: {', '.join(self.tools)}")
        if not isinstance(arguments, dict):
            return ToolResult("error: arguments must be a JSON object")
        result = anyio.from_thread.run(self.client.call_tool, name, arguments)
        self.calls.append(f"{name}{' (is_error)' if result.is_error else ''}")
        if result.is_error:
            return ToolResult(result.content[0].text)
        reply = result.structured_content
        return ToolResult(reply["text"], answer_from(reply) if reply["answer"] else None)


async def ask_through_server(server: MCPServer, question: str, model: Model, max_steps: int = 4
                             ) -> tuple[Trace, list[str]]:
    """Answer one question with the book's agent loop, every tool on `server`. Returns the trace and the calls."""
    async with Client(server) as client:
        listed_tools = [tool.name for tool in (await client.list_tools()).tools]
        # In the in-process toolbox's order, so an unknown tool's message is the text the model saw in process.
        tools = sorted(listed_tools, key=lambda t: IN_PROCESS_ORDER.index(t) if t in IN_PROCESS_ORDER else 99)
        listed = await client.call_tool("list_metrics", {})
        toolbox = ServerToolbox(client, tools)
        toolbox.calls.append("list_metrics")
        system = metrics_first_prompt(listed.structured_content["text"])
        trace = await anyio.to_thread.run_sync(lambda: run_agent(question, system, model, toolbox, max_steps))
    return trace, toolbox.calls
