"""Score each layer set on the dev split's answer questions, replaying the recorded model's SQL for each."""
from collections import Counter

from lib.context import LAYER_SETS, build_context, grade_with_context, layer_set_name
from lib.golden import load_golden
from lib.model import RecordedModel
from lib.warehouse import connect

con = connect()
model = RecordedModel("context-layers")
dev_split = [q for q in load_golden() if q.split == "dev"]
dev = [q for q in dev_split if q.kind == "answer"]
print(f"dev split questions: {len(dev_split)}")
print(f"dev questions: {len(dev)}")
print(f"dev questions to decline: {len(dev_split) - len(dev)}")

grid = {}
for layers in LAYER_SETS:
    name = layer_set_name(layers)
    grid[name] = [grade_with_context(con, model, q, layers) for q in dev]
    counts = Counter(grid[name])
    tokens = sum(build_context(con, q.question, layers).tokens for q in dev) // len(dev)
    print(f"{name}: correct {counts['correct']}, wrong {counts['wrong']}, error {counts['error']}")
    print(f"{name} correct: {counts['correct']}")
    print(f"{name} error: {counts['error']}")
    print(f"{name} tokens: {tokens}")

print("question  " + "  ".join(f"{i + 1}" for i in range(len(LAYER_SETS))))
for i, q in enumerate(dev):
    print(f"{q.question_id}    " + "  ".join(grid[name][i][0] for name in grid))

# What the verified queries changed, against the run with the glossary.
before, after = grid[layer_set_name(LAYER_SETS[2])], grid[layer_set_name(LAYER_SETS[3])]
fixed = [q.question_id for q, was, now in zip(dev, before, after) if was != "correct" and now == "correct"]
broken = [q.question_id for q, was, now in zip(dev, before, after) if was == "correct" and now != "correct"]
print(f"fixed by verified queries: {len(fixed)}")
print(f"fixed by verified queries, IDs: {', '.join(fixed)}")
print(f"broken by verified queries: {len(broken)}")
