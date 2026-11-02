"""Choose the best layer set on the dev split, then score it once on the held-out test split beside the schema alone."""
from collections import Counter

from lib.context import LAYER_SETS, QueryIndex, grade_with_context, layer_set_name, load_verified_queries
from lib.golden import load_golden
from lib.model import RecordedModel
from lib.warehouse import connect

con = connect()
questions = [q for q in load_golden() if q.kind == "answer"]
dev = [q for q in questions if q.split == "dev"]
test = [q for q in questions if q.split == "test"]

dev_model = RecordedModel("context-layers")
dev_correct = {layers: sum(grade_with_context(con, dev_model, q, layers) == "correct" for q in dev)
               for layers in LAYER_SETS}
best = max(LAYER_SETS, key=lambda layers: (dev_correct[layers], -len(layers)))   # ties go to fewer layers
print(f"best on dev: {layer_set_name(best)}")
print(f"best on dev correct: {dev_correct[best]} of {len(dev)}")

test_model = RecordedModel("context-layers-test")
print(f"test questions: {len(test)}")
print(f"test question IDs: {', '.join(q.question_id for q in test)}")
for name, layers in (("schema", LAYER_SETS[0]), ("best", best)):
    counts = Counter(grade_with_context(con, test_model, q, layers) for q in test)
    print(f"test {name}: correct {counts['correct']}, wrong {counts['wrong']}, error {counts['error']}")
    print(f"test {name} correct: {counts['correct']}")

# How close each split's questions sit to the verified queries, by the retriever's own score.
index = QueryIndex(load_verified_queries())
for split, qs in (("dev", dev), ("test", test)):
    best_match = [(index.search(q.question, k=1, min_score=0.0)[0], q) for q in qs]
    print(f"{split} mean top retrieval score: {sum(score for (score, _), _ in best_match) / len(qs):.2f}")
    print(f"{split} questions with no verified query kept: {sum(not index.search(q.question) for q in qs)}")
    (score, query), q = max(best_match, key=lambda pair: pair[0][0])
    print(f"{split} closest pair: {q.question_id} and {query.name}")
    print(f"{split} closest score: {score:.3f}")
