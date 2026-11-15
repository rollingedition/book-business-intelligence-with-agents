"""Score schema-only SQL on three public DABstep tasks and on the shop's dev questions, with the same model.
The point about task 49 rests on its "SQL ran: False" line, which the assert checks, and on the two top-country lines
that follow it, which read the same fraud data by two definitions."""
from lib import dabstep
from lib.golden import load_golden, schema_only_outcome
from lib.model import RecordedModel
from lib.warehouse import connect, describe_schema

payments = dabstep.connect()
runs = [dabstep.answer_task(payments, RecordedModel("dabstep-runs"), task) for task in dabstep.load_tasks()]  # replays recorded replies
for run in runs:
    print(f"task {run.task.task_id}: answered {run.answer[:40]!r}, expected {run.task.answer!r}, correct: {run.correct}")
    print(f"task {run.task.task_id} SQL ran: {not run.result.startswith('error')}")
print(f"DABstep correct: {sum(run.correct for run in runs)} of {len(runs)}")
task49 = next(run for run in runs if str(run.task.task_id) == "49")
assert task49.result.startswith("error")  # a query that fails comes back as text that starts with "error"

# Task 49 asks for the top country "for fraud". DABstep's manual defines fraud as fraudulent volume over total volume.
by_count, by_volume = payments.execute("""
    SELECT arg_max(ip_country, frauds), arg_max(ip_country, fraud_share) FROM (
        SELECT ip_country, count(*) FILTER (has_fraudulent_dispute) AS frauds,
               sum(eur_amount) FILTER (has_fraudulent_dispute) / sum(eur_amount) AS fraud_share
        FROM payments GROUP BY ip_country)""").fetchall()[0]  # one row: the top country by each measure
print(f"task 49 top by count of frauds: {by_count}")
print(f"task 49 top by fraud volume ratio: {by_volume}")

con = connect()
schema, model = describe_schema(con), RecordedModel("schema-only-sql")  # the recorded replies to the schema-only prompt
dev = [q for q in load_golden() if q.split == "dev"]
outcomes = [schema_only_outcome(con, model, schema, q) for q in dev]
print(f"shop dev correct: {outcomes.count('correct')} of {len(dev)}")
