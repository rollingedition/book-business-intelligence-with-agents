"""Draw the shop's five semantic models as boxes, with an arrow from each model with a foreign entity to the model
where that entity is primary. An arrow is marked many, and drawn in accent, where some primary row has more than one
row on the foreign side. A sum that follows an arrow repeats nothing; a sum on the primary side joined back across a
many arrow repeats once per row. The printed lines are the facts the prose states."""
import lib  # noqa: F401  (first, so threads and seeds are fixed before any numerical library loads)
from matplotlib.patches import FancyBboxPatch

from lib.figures import ACCENT, INK, MUTED, new_figure, save
from lib.semantic import load
from lib.warehouse import connect

# Hand-chosen box centres and label anchors, so the drawing is fixed.
POS = {"customers": (0.13, 0.78), "orders": (0.50, 0.78), "refunds": (0.13, 0.20),
       "order_lines": (0.50, 0.20), "products": (0.87, 0.20)}
LABEL = {("orders", "customers"): (0.315, 0.90, "center"), ("order_lines", "orders"): (0.53, 0.49, "left"),
         ("order_lines", "products"): (0.685, 0.05, "center"), ("refunds", "orders"): (0.36, 0.60, "right")}

layer, con = load(), connect()
owner = {m.primary_entity: m for m in layer.semantic_models.values()}   # the model where each entity is primary
fig, ax = new_figure(height=3.4)
ax.set_xlim(0, 1), ax.set_ylim(0, 1), ax.set_axis_off()
boxes = {n: ax.add_patch(FancyBboxPatch((x - 0.12, y - 0.085), 0.24, 0.17, fc="none", ec=INK,
                                        boxstyle="round,pad=0,rounding_size=0.02")) for n, (x, y) in POS.items()}
for name, (x, y) in POS.items(): ax.text(x, y, name, ha="center", va="center", color=INK, fontsize=10)
fan_out = 0
for model in layer.semantic_models.values():
    for entity in (e for e in model.entities.values() if e.type == "foreign"):
        target = owner[entity.name]
        groups = f"SELECT count(*) AS n FROM {model.table} GROUP BY {entity.expr}"
        most = con.execute(f"SELECT max(n) FROM ({groups})").fetchone()[0]
        many = most > 1
        fan_out += many
        if entity.name == "order":  # the two order hops the prose quotes
            per = con.execute(f"SELECT count(*) * 1.0 / (SELECT count(*) FROM {target.table}) FROM {model.table}")
            print(f"{model.name} rows per order: {per.fetchone()[0]:.2f}\nmost {model.name} rows for one order: {most}")
        # a many hop is solid and accent; the other is dashed too, so colour is never alone
        look = dict(color=ACCENT, lw=2.2) if many else dict(color=MUTED, lw=1.2, ls="--")
        ax.annotate("", xy=POS[target.name], xytext=POS[model.name], xycoords="axes fraction",
                    arrowprops=dict(arrowstyle="-|>", patchA=boxes[model.name], patchB=boxes[target.name], **look))
        text = (f"{entity.name}: many {model.name} per {entity.name}" if many
                else f"{entity.name}: {model.name} per {entity.name}, at most {most}")
        x, y, align = LABEL[(model.name, target.name)]
        ax.text(x, y, text, ha=align, va="center", color=look["color"], fontsize=9)
print(f"hops with many rows per primary row: {fan_out}")
save(fig, "entity-graph")
