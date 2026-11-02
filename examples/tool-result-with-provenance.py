"""What a host receives from query_metric: an answer with its provenance as structured content, a request the model
can correct as a tool error, and a request the role may not make as an answer that declines."""
import json

import anyio
from mcp import Client

from lib.semantic import load
from lib.semantic_server import build_server
from lib.warehouse import connect

con, layer = connect(), load()
asks = {"finance, refund rate": ("finance", {"metrics": ["refund_rate"], "group_by": ["order__region"],
                                             "filters": {"metric_time__fiscal_year": 2026}}),
        "finance, misspelt dimension": ("finance", {"metrics": ["refund_rate"], "group_by": ["order_region"]}),
        "support, net revenue": ("support", {"metrics": ["net_revenue"], "filters": {"metric_time__year": 2025}})}


async def main():
    for name, (role, request) in asks.items():
        async with Client(build_server(role, shop=con, layer=layer)) as client:
            tool = next(t for t in (await client.list_tools()).tools if t.name == "query_metric")
            result = await client.call_tool("query_metric", request)
        print(f"{name}, is_error: {result.is_error}")
        if result.is_error:
            print(f"{name}, text: {result.content[0].text}")
            continue
        answer = result.structured_content["answer"]
        print(f"{name}, answered: {answer['answered']}")
        print(f"{name}, text block is the same JSON: {json.loads(result.content[0].text) == result.structured_content}")
        if answer["answered"]:
            print(f"{name}, rows: {', '.join(f'{region} {rate:.2%}' for region, rate in answer['rows'])}")
            print(f"{name}, provenance fields: {', '.join(answer['provenance'])}")
            print(f"{name}, provenance: {json.dumps({k: v for k, v in answer['provenance'].items() if k != 'sql'})}")
        else:
            print(f"{name}, reason: {answer['reason']}")
    print(f"output schema requires: {', '.join(tool.output_schema['required'])}")


anyio.run(main)
