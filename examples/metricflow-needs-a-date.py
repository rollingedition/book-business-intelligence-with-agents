"""Show that MetricFlow won't build its engine when a fact's semantic model has no date of its own."""
import shutil
import tempfile
from pathlib import Path

import yaml

from lib.metricflow_bridge import engine
from lib.semantic import SEMANTIC_DIR
from lib.warehouse import connect

con = connect()
print(f"MetricFlow with the shop's YAML: {type(engine(con)).__name__}")

# A copy in which order_lines reads analytics.fct_order_lines, which has no order day, and declares no date.
with tempfile.TemporaryDirectory() as tmp:
    folder = Path(tmp) / "semantic"
    shutil.copytree(SEMANTIC_DIR, folder)
    path = folder / "order_lines.yml"
    document = yaml.safe_load(path.read_text())
    lines_model = document["semantic_model"]
    lines_model["node_relation"] = {"schema_name": "analytics", "alias": "fct_order_lines"}
    del lines_model["defaults"], lines_model["dimensions"]
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    try:
        engine(con, folder)
        print("MetricFlow without a date on order_lines: built")
    except Exception as e:
        print(f"MetricFlow without a date on order_lines: {type(e).__name__}")
        print(f"its message begins: {str(e).splitlines()[0]}")
