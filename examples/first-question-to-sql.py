"""Send the warehouse's schema and one question to the recorded model, and print the SQL it wrote."""
from lib.golden import load_golden
from lib.model import RecordedModel
from lib.prompts import schema_only_messages
from lib.warehouse import connect, describe_schema

schema = describe_schema(connect())
question = next(q for q in load_golden() if q.question_id == "gq-002")
messages = schema_only_messages(schema, question.question)

print(f"tables in the prompt: {schema.count('CREATE TABLE')}")
print(next(line for line in schema.splitlines() if "analytics.fct_orders " in line))

model = RecordedModel("schema-only-sql")       # replays the pinned model's real replies
call = model.call_for(messages)
print(f"prompt tokens: {call['prompt_tokens']}")
print(f"question: {question.question}")
print(call["reply"])
