"""Count what the golden set covers in each split: kinds, roles and the warehouse's traps."""
from collections import Counter

from lib.golden import load_golden

questions = load_golden()
splits = ("dev", "test")
for split in splits:
    print(f"{split} questions: {sum(q.split == split for q in questions)}")
print("split  answer  decline  forbidden")
for split in splits:
    kinds = Counter(q.kind for q in questions if q.split == split)
    print(f"{split:<5}  {kinds['answer']:>6}  {kinds['decline']:>7}  {kinds['forbidden']:>9}")

for split in splits:
    roles = Counter(q.role for q in questions if q.split == split and q.kind == "answer")
    print(f"{split} answers by role: {dict(sorted(roles.items()))}")

traps = {split: Counter(t for q in questions if q.split == split for t in q.traps) for split in splits}
print("trap                  dev  test")
for trap in sorted(traps["dev"] | traps["test"]):
    print(f"{trap:<20}  {traps['dev'][trap]:>3}  {traps['test'][trap]:>4}")
missing = sorted(t for t in traps["dev"] | traps["test"] if not traps["dev"][t] or not traps["test"][t])
print(f"traps missing from a split: {', '.join(missing) or 'none'}")
