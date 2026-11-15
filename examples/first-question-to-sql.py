"""Send the warehouse's schema and one question to the recorded model, and print the SQL it wrote. The prose reads that SQL for its table, its columns and its date filter, against the `analytics.fct_orders` line printed above it."""
from lib.golden import load_golden
from lib.model import RecordedModel
from lib.prompts import schema_only_messages
from lib.warehouse import connect, describe_schema

schema = describe_schema(connect())
# gq-002 is net revenue in each region in March 2026, the question the prose follows.
question = next(q for q in load_golden() if q.question_id == "gq-002")
messages = schema_only_messages(schema, question.question)

# Each table's schema is one CREATE TABLE statement, so counting them counts the tables.
print(f"tables in the prompt: {schema.count('CREATE TABLE')}")
# The trailing space makes this match the whole table name, not a longer one that starts the same way.
print(next(line for line in schema.splitlines() if "analytics.fct_orders " in line))

model = RecordedModel("schema-only-sql")       # replays the pinned model's real replies
call = model.call_for(messages)
print(f"prompt tokens: {call['prompt_tokens']}")
print(f"question: {question.question}")
print(call["reply"])
