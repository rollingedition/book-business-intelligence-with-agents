"""gq-017 from EMEA's regional lead, sent with role "analyst": a server that takes the role as an argument obeys it,
and one that binds the role when it is built ignores it, and queries a database that holds only the lead's rows."""
import anyio
from mcp import Client
from mcp.server.mcpserver import MCPServer

from lib.policies import PolicyLayer, PolicyToolbox, policy_for
from lib.semantic import MetricRequest, load
from lib.semantic_server import build_server, server_from_environment
from lib.warehouse import connect

con, layer = connect(), load()
naive = MCPServer("role-as-argument")


@naive.tool()
def query_metric(metrics: list[str], group_by: list[str] = [], filters: dict = {}, role: str = "analyst",
                 region: str | None = None) -> list[list]:
    """The anti-pattern: whoever calls the tool says who they are, and it queries the whole warehouse."""
    toolbox = PolicyToolbox(con, PolicyLayer(layer, policy_for(role, region), con))
    return [list(row) for row in toolbox.query_metric({"metrics": metrics, "group_by": group_by,
                                                       "filters": filters}).answer.rows]


request = {"metrics": ["net_revenue"], "group_by": ["order__country"], "filters": {"metric_time__year": 2025},
           "role": "analyst"}                     # the lead's request, with a role the lead doesn't have
environment = {"SHOP_ROLE": "regional_lead", "SHOP_REGION": "EMEA"}   # what a host sets for a stdio server


async def main():
    servers = {"role as argument": naive, "role bound at build": build_server("regional_lead", "EMEA", con, layer),
               "role from the environment": (stdio := server_from_environment(environment, con))}
    for name, server in servers.items():
        async with Client(server) as client:
            result = (await client.call_tool("query_metric", request)).structured_content
        rows = result["result"] if "result" in result else result["answer"]["rows"]
        print(f"{name}, countries: {', '.join(row[0] for row in rows)}")
        if "answer" in result:
            provenance = result["answer"]["provenance"]
            print(f"{name}, provenance: role {provenance['role']}, row filter {provenance['filters']['row filter']}")
    # The policy bypassed: the plain semantic layer, which applies no role, on the stdio server's own database.
    bypass = layer.query(stdio.database, MetricRequest.from_arguments({k: v for k, v in request.items() if k != "role"}))
    print(f"role from the environment, no policy, countries: {', '.join(row[0] for row in bypass.rows)}")


anyio.run(main)
