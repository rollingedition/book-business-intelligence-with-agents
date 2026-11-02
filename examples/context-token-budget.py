"""Fit one question's layered context to a token budget, and check the token estimate against the model's count."""
from lib.context import LAYERS, build_context, estimate_tokens
from lib.golden import load_golden
from lib.model import RecordedModel
from lib.prompts import layered_sql_messages
from lib.warehouse import connect

con = connect()
question = next(q for q in load_golden() if q.question_id == "gq-009").question
full = build_context(con, question)
for layer, tokens in full.layer_tokens().items():
    print(f"{layer} tokens (estimated): {tokens}")

messages = layered_sql_messages(full.text, question)
call = RecordedModel("context-layers").call_for(messages)
print(f"prompt tokens (estimated): {estimate_tokens(''.join(m['content'] for m in messages))}")
print(f"prompt tokens (model's tokenizer): {call['prompt_tokens']}")

budget = 2400
for name, priority in (("default", LAYERS), ("examples first", ("schema", "columns", "verified", "glossary"))):
    fitted = build_context(con, question, layers=priority, budget=budget)
    kept = {layer: len(items) for layer, items in fitted.items.items()}
    print(f"{name} priority: {fitted.tokens} tokens, kept {kept}")
    print(f"{name} dropped: {len(fitted.dropped)}")
print(f"render order: {', '.join(layer for layer, items in fitted.items.items() if items)}, then the question")
