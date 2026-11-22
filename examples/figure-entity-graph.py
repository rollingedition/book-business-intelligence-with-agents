"""Draw the shop's five semantic models as boxes, with an arrow from each model with a foreign entity to the model where that entity is primary. An arrow is solid accent where its foreign side has many rows per primary row, so a per-order sum over it would repeat; the printed `rows per` lines are the facts the prose states."""
import lib  # noqa: F401  (first, so threads and seeds are fixed before any numerical library loads)
from matplotlib.patches import FancyBboxPatch

from lib.figures import ACCENT, INK, MUTED, new_figure, save
from lib.semantic import load
from lib.warehouse import connect

POSITIONS = {"customers": (0.13, 0.78), "orders": (0.50, 0.78), "refunds": (0.13, 0.20),   # hand-chosen, so the drawing is fixed
             "order_lines": (0.50, 0.20), "products": (0.87, 0.20)}
LABEL_AT = {("orders", "customers"): (0.315, 0.90, "center"), ("order_lines", "orders"): (0.53, 0.49, "left"),
            ("order_lines", "products"): (0.685, 0.05, "center"), ("refunds", "orders"): (0.36, 0.60, "right")}

layer, con = load(), connect()
owner = {m.primary_entity: m for m in layer.semantic_models.values()}   # the model where each entity is primary
fig, ax = new_figure(height=3.4)
ax.set_xlim(0, 1), ax.set_ylim(0, 1), ax.set_axis_off()
boxes = {}
for name, (x, y) in POSITIONS.items():
    boxes[name] = ax.add_patch(FancyBboxPatch((x - 0.12, y - 0.085), 0.24, 0.17, boxstyle="round,pad=0,rounding_size=0.02", fc="none", ec=INK))
    ax.text(x, y + 0.025, name, ha="center", va="center", color=INK, fontsize=10)
    ax.text(x, y - 0.035, layer.semantic_models[name].table, ha="center", va="center", color=MUTED, fontsize=8)
rows = {m.table: con.execute(f"SELECT count(*) FROM {m.table}").fetchone()[0] for m in layer.semantic_models.values()}

fan_out = 0
for model in layer.semantic_models.values():
    for entity in (e for e in model.entities.values() if e.type == "foreign"):
        target = owner[entity.name]
        ratio = rows[model.table] / rows[target.table]          # rows of the foreign side per primary row
        most = con.execute(f"SELECT max(n) FROM (SELECT count(*) AS n FROM {model.table} GROUP BY {entity.expr})").fetchone()[0]
        many = ratio > 1                                        # a sum on the primary side would repeat
        fan_out += many
        print(f"edge: {model.name} -> {target.name} on {entity.name}")
        print(f"{model.name} rows per {entity.name}: {ratio:.2f}")
        print(f"most {model.name} rows for one {entity.name}: {most}")
        color, width, style = (ACCENT, 2.2, "-") if many else (MUTED, 1.2, "--")   # dashed too, so colour isn't alone
        ax.annotate("", xy=POSITIONS[target.name], xytext=POSITIONS[model.name], xycoords="axes fraction",
                    textcoords="axes fraction", arrowprops=dict(arrowstyle="-|>", color=color, lw=width, linestyle=style,
                                                                shrinkA=0, shrinkB=0, patchA=boxes[model.name],
                                                                patchB=boxes[target.name]))
        text = f"{entity.name}: many {model.name} per {entity.name}" if many else f"{entity.name}: {ratio:.2f} {model.name} per {entity.name}"
        x, y, align = LABEL_AT[(model.name, target.name)]
        ax.text(x, y, text, ha=align, va="center", color=color, fontsize=9)
print(f"hops with many rows per primary row: {fan_out}")
save(fig, "entity-graph")
