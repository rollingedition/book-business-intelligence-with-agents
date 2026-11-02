"""Load the shop's semantic layer from YAML, list what each semantic model declares, and check it against the warehouse."""
from dataclasses import replace

from lib.semantic import Entity, SemanticLayer, load
from lib.warehouse import connect

layer = load()                   # reads examples/data/semantic/*.yml and validates the definitions
print(f"semantic models: {len(layer.semantic_models)}")
print(f"metrics: {len(layer.metrics)}")
for model in layer.semantic_models.values():
    entities = ", ".join(f"{e.name} ({e.type})" for e in model.entities.values())
    print(f"{model.name}: {model.table}; entities: {entities}; dimensions: {', '.join(model.dimensions) or 'none'}")

metric = layer.metrics["net_revenue"]
print(f"net_revenue: {metric.agg} of {metric.expr} in {metric.semantic_model}, where {metric.filter}")

con = connect()
print(f"problems in the shop's definitions: {len(layer.check(con))}")

# A layer with one mistake: the lines declare `order` as their primary entity, as if each order had one line.
lines = layer.semantic_models["order_lines"]
wrong = replace(lines, entities={"order": Entity("order", "primary", "order_id"),
                                 "product": lines.entities["product"]})
for problem in SemanticLayer({"order_lines": wrong}, {}, layer.time_spine).check(con):
    print(f"problem: {problem}")
