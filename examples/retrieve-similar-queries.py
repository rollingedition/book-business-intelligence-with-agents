"""Retrieve the verified queries most like a question, by TF-IDF over the masked question's words. The matches kept at the
0.4 default show that a threshold can leave a question with no example, and the masked phrases show what masking does."""
from lib.context import QueryIndex, load_verified_queries, question_terms

queries = load_verified_queries()
index = QueryIndex(queries)
print(f"verified queries: {len(queries)}")

for label, question in (("aov", "What was the average order value in each region in March 2026?"),
                        ("parcels", "Which warehouse ships the most parcels?")):
    print(f"question: {question}")
    print(f"masked terms: {' '.join(question_terms(question))}")
    for score, query in index.search(question, k=3, min_score=0.0):     # no threshold here, so the scores show the gap
        print(f"  {score:.3f}  {query.name}")
    print(f"{label} matches kept: {len(index.search(question))}")         # the default threshold, 0.4, is the one the book uses

# Months and numbers are masked; "calendar" and "year" are not common words, and "Q3" is not masked at all.
for phrase in ("March 2026", "January 2025", "calendar year 2024", "EMEA in Q3"):
    print(f"masked \"{phrase}\": {' '.join(question_terms(phrase))}")
