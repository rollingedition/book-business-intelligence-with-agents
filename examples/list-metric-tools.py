"""The semantic layer as an MCP server: the tools it lists, what query_metric takes, and each role's catalog."""
import anyio
from mcp import Client

from lib.metric_tools import catalog
from lib.policies import PolicyLayer, policy_for
from lib.semantic import load
from lib.semantic_server import build_server
from lib.warehouse import connect

con, layer = connect(), load()


async def main():
    listed = {}
    for role in ("analyst", "support"):
        async with Client(build_server(role, shop=con, layer=layer)) as client:   # in memory: no port, no process
            tools = (await client.list_tools()).tools
            text = (await client.call_tool("list_metrics", {})).structured_content["text"]
        listed[role] = [t.name for t in tools]
        metrics = [line[2:].split(":")[0] for line in text.splitlines()]
        print(f"{role}, tools: {', '.join(listed[role])}")
        print(f"{role}, metrics in list_metrics: {len(metrics)}")
        print(f"{role}, metrics: {', '.join(metrics)}")
        in_process = catalog(PolicyLayer(layer, policy_for(role), con))
        print(f"{role}, same catalog as the in-process agent: {text == in_process}")
    query = next(t for t in tools if t.name == "query_metric")
    print(f"query_metric inputs: {', '.join(query.input_schema['properties'])}")
    print(f"query_metric requires: {', '.join(query.input_schema['required'])}")
    print(f"tools marked read-only: {sum(t.annotations.read_only_hint for t in tools)} of {len(tools)}")
    print(f"tools with a role input: {sum('role' in t.input_schema['properties'] for t in tools)}")
    print(f"same tool list for both roles: {listed['analyst'] == listed['support']}")


anyio.run(main)
