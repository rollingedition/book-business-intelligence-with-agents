"""An upstream rename of one column, caught by three checks that need no model, and the one-line fix."""
import shutil
import tempfile
from pathlib import Path

from lib.golden import load_golden
from lib.regressions import migrated, schema_checks
from lib.semantic import SEMANTIC_DIR, load

RENAME = "ALTER TABLE analytics.fct_orders RENAME COLUMN net_revenue_eur TO net_revenue_ex_tax_eur"
con = migrated(RENAME)
golden = load_golden()
dev = [q for q in golden if q.split == "dev"]

failed = schema_checks(con, load(), golden)
print(f"golden SQL that fails: {len(failed['golden SQL'])} of {sum(bool(q.golden_sql) for q in golden)}")
print(f"golden questions affected: {', '.join(failed['golden SQL'])}")
print(f"metrics that fail: {', '.join(failed['metrics'])}")
replays = schema_checks(con, load(), dev)["replays"]
print(f"recorded dev runs that no longer replay: {len(replays)} of {sum(q.kind != 'forbidden' for q in dev)}")
print(f"runs that stop: {', '.join(replays)}")

# The fix: the metric's expr names the new column. A copy of the YAML stands in for the commit that changes it.
fixed = Path(tempfile.mkdtemp()) / "semantic"
shutil.copytree(SEMANTIC_DIR, fixed)
metrics = fixed / "metrics.yml"
metrics.write_text(metrics.read_text().replace("expr: net_revenue_eur", "expr: net_revenue_ex_tax_eur"))
after = schema_checks(con, load(fixed), dev)
print(f"after the fix, metrics that fail: {', '.join(after['metrics']) or 'none'}")
print(f"after the fix, recorded dev runs that no longer replay: {len(after['replays'])}")
shutil.rmtree(fixed.parent)
