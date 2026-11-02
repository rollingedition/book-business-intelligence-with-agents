"""Retrieve the verified queries most like a question, by TF-IDF over masked question words."""
from lib.context import QueryIndex, load_verified_queries, question_terms

queries = load_verified_queries()
index = QueryIndex(queries)
print(f"verified queries: {len(queries)}")

for label, question in (("aov", "What was the average order value in each region in March 2026?"),
                        ("parcels", "Which warehouse ships the most parcels?")):
    print(f"question: {question}")
    print(f"masked terms: {' '.join(question_terms(question))}")
    for score, query in index.search(question, k=3, min_score=0.0):
        print(f"  {score:.3f}  {query.name}")
    print(f"{label} matches kept: {len(index.search(question))}")

# What masking does to the words that name a time or a region, and what it leaves.
for phrase in ("March 2026", "January 2025", "calendar year 2024", "EMEA in Q3"):
    print(f"masked \"{phrase}\": {' '.join(question_terms(phrase))}")
