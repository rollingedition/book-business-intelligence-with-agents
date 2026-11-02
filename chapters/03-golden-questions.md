---
chapter_id: golden-questions
---

# Build golden questions from your own work

By the end of this chapter, you can write golden questions from the questions people in your business ask, each with its golden SQL, the role that asks it and the kind of answer it needs. You can compare an agent's results with golden results rather than comparing SQL text, check the gold itself before you trust it, and say why a score on a public benchmark isn't a score on your warehouse.

Chapter 1 scored two approaches on five golden questions, and five questions can only serve as a smoke test. A change to the prompt that fixes or breaks one question moves the score by a fifth, and a change that fixes one and breaks another doesn't move it at all. Nothing in five questions tests a decline for an ambiguous question or a question the asker's role may not see. Every later chapter in this book changes one part of the agent and claims that the change helped. Those claims need a set large enough to measure, with questions that cover the shop's traps, its roles and its declines, and with a part held back that no change is tuned on.

Chapter 2 added eleven more, each aimed at one trap. This chapter keeps all sixteen and builds the set to {{out:load-golden-questions:golden questions}} golden questions about the shop, the online outdoor-gear shop whose generated warehouse the book's examples query. It starts with the case for writing your own questions at all, since public benchmarks exist and are cheaper to download than to write.

## Why a public benchmark isn't your test {#benchmarks-are-not-your-test}

A public benchmark for text-to-SQL or data agents gives you questions, a database and a gold answer for each question, and a score that others have reported on the same set. That makes it useful for comparing models with each other. It doesn't tell you how an agent will do on your warehouse, for two reasons. The benchmark's questions, data and definitions are someone else's, so a high score says the model handles their work. And the gold answers are claims written by people, so the score also measures how often the gold is right.

The second reason has been measured. An audit presented at CIDR 2026 had experts check each gold query against its question and schema, run it, and run its subqueries. It found annotation errors in 52.8% of BIRD Mini-Dev, in its first, 500-question version, and in 66.1% of the 121 Spider 2.0-Snow problems whose gold SQL is public, in its `spider2-snow-0713` file ([Jin et al., CIDR 2026](https://vldb.org/cidrdb/papers/2026/p5-jin.pdf)). The most common error was gold SQL that misread the data or the schema. When the authors corrected 100 BIRD Dev problems and re-ran five open-source agents, scores moved by −3% to +31% in relative terms, and one agent went from fourth place to first. Benchmarks also change under you: the BIRD team revised Mini-Dev on 26 and 27 October 2026, correcting reference SQL and replacing questions, and kept the 2025 release as an archive ([BIRD Mini-Dev](https://huggingface.co/datasets/birdsql/bird_mini_dev)). Those figures are the paper's measurements, not ours. The book cites BIRD and Spider and doesn't ship them, because it ships only data under CC BY 4.0, CC0 or its own licence, and BIRD is CC BY-SA 4.0.

To see the first reason on data the book can ship, this chapter uses a small part of DABstep, the Data Agent Benchmark for Multi-step Reasoning, which is licensed CC BY 4.0. DABstep asks questions about a payments processor's transactions, scores only the final answer, and keeps most of its tasks hidden for its leaderboard ([the paper](https://arxiv.org/abs/2506.23719)). The dataset holds 450 tasks, and only its 10 dev tasks have public answers ([the dataset](https://huggingface.co/datasets/adyen/DABstep)). The book's copy, in `examples/data/dabstep/`, holds the three dev tasks at DABstep's lower difficulty level and the full payments table of 138,236 transactions, without four identifier columns that no task needs: hashed IP addresses, shopper emails and card numbers, and each card's bank identification number. `SOURCE.md` there gives the pinned revision of [the dataset](https://huggingface.co/datasets/adyen/DABstep) and every change, and `LICENSE` is the dataset's own notice. The merchants in the payments table are fictional businesses, and their names come from DABstep as published. `lib/dabstep.py` loads the table into DuckDB.

The example runs [the schema-only approach from chapter 1](#ask-for-sql) on both sets, with the same recorded model, Qwen3-4B-Instruct-2507: the model sees a table's schema and a question, writes SQL, and the SQL runs. On DABstep, the model then reads the query's result and gives a final answer in the format the task asks for. The recording `dabstep-runs` holds those replies.

[Example: public-vs-own-score](../examples/public-vs-own-score.py)

Schema-only SQL gets {{out:public-vs-own-score:DABstep correct}} DABstep tasks right, scored by a simplified version of DABstep's quasi-exact match, and {{out:public-vs-own-score:shop dev correct}} dev questions. Neither number predicts the other, and the gap isn't the point: the two sets ask different things. DABstep's tasks are about one table with no fiscal calendar, no cancelled orders and no legacy mart. The shop's questions fail on exactly those.

Task 49 shows what a gold depends on. It asks for the top country "for fraud", and its gold is `BE`. Counted by the number of fraudulent transactions, the top country is `{{out:public-vs-own-score:task 49 top by count of frauds}}`. Measured as the fraudulent share of payment volume, it's `{{out:public-vs-own-score:task 49 top by fraud volume ratio}}`. DABstep's manual settles it: fraud is "the ratio of fraudulent volume over total volume" ([the manual](https://huggingface.co/datasets/adyen/DABstep/blob/1d740a52b8a41ba6fdd4d4435120a0429023dd24/data/context/manual.md)). The question alone doesn't. Here the model's SQL failed to run, `task 49 SQL ran: {{out:public-vs-own-score:task 49 SQL ran}}`, and it named a country anyway. Task 70's gold is `Not Applicable`. As we read the manual, it describes fraud-related fees but no fine. The model replied with a query instead of an answer.

**Working rule:** Use public benchmarks to compare models on a common task, and never as evidence that an agent works on your warehouse. Cite the benchmark's version with any score you quote, since gold sets get corrected. Measure your own agent on golden questions written from your own work, with your definitions, and expect the two scores to disagree.

## Write questions from the work people do {#write-golden-questions}

A [public benchmark measures someone else's work](#benchmarks-are-not-your-test), so the set that measures the shop's agent has to come from the shop. The best source of golden questions is the questions people already ask: requests in the analytics team's queue, the numbers in a monthly finance pack, the filters people set on dashboards. Write each in the asker's words, not tidied into the schema's vocabulary, because the agent will hear the asker's words. Then write the golden SQL that answers it under the business's definitions, and check it.

Each golden question in this book holds the same fields. The `question` is the asker's text. The `role` is who asks, which decides what they may see, and a `regional_lead` also carries their `region`. The `kind` says what a right answer looks like: `answer` when the warehouse can answer it, `decline` when it can't, and `forbidden` when the role may not see the answer. A decline also has a `decline_type`, `ambiguous` or `unanswerable`. An answerable question has `golden_sql`, a comparison rule (`order_matters` and a `tolerance`), and a `note` that names the definition the gold follows. Each question also lists the warehouse's `traps` it tests, such as `fiscal-calendar` or `late-refunds`, and sits in the `dev` or the `test` split.

The shop's set lives in `examples/data/golden/questions.toml`, and `load_golden()` in `lib/golden.py` reads it into `GoldenQuestion` objects. The file's header states the two definitions most questions depend on. Net revenue is the finance team's: euros after discounts and before tax, from real orders that weren't cancelled, on the order's local business day. An order count includes cancelled orders and leaves out test orders.

[Example: load-golden-questions](../examples/load-golden-questions.py)

The set holds {{out:load-golden-questions:golden questions}} questions: {{out:load-golden-questions:answer}} to answer, {{out:load-golden-questions:decline}} to decline and {{out:load-golden-questions:forbidden}} that the asking role may not see. Of the declines, {{out:load-golden-questions:decline, ambiguous}} are ambiguous and {{out:load-golden-questions:decline, unanswerable}} are unanswerable. Every role in the case asks at least one question.

The question the example prints, `gq-018`, is one a finance team asks after every month closes. Its golden SQL is short, and its value is in the definition: refunds belong to the month the order was placed, including refunds made weeks later. The example also computes the other reading. Refunds on orders placed in March 2026 come to {{out:load-golden-questions:refunded on orders placed in March 2026}} euros, and a reasonable query that groups refunds by the month they were made returns {{out:load-golden-questions:refunded in March 2026, by refund month}}. Both numbers are useful. The golden question records which one this asker means, and its note says so in words a reviewer can check without reading SQL.

Most of the work in writing these is deciding what the asker meant and finding the definition someone owns. Write the note first. If you can't write it in one sentence, the question is ambiguous, and it becomes a decline.

**Working rule:** Collect golden questions from real requests, keep the asker's wording, and give each one a role, a kind and a note that names the definition its gold follows. Write the golden SQL against the marts the agent will use, and have the person who owns the definition read the note. Expect to spend more time on the definitions than on the SQL.

## Compare results, not SQL text {#compare-results-not-sql}

With [the golden questions written](#write-golden-questions), the next decision is how to tell whether an agent's answer matches. Comparing the agent's SQL with the golden SQL fails both ways. Two queries can be written differently and return the same rows, and two queries a few words apart can return different numbers. What the asker sees is the result, so that's what to compare. An execution match means the agent's result equals the golden result under the question's comparison rule. Benchmarks do the same: BIRD reports execution accuracy, which compares the rows each query returns ([`calculate_ex` in BIRD's evaluation code](https://github.com/bird-bench/mini_dev/blob/1c49a375e76c471e218564da3f4617513d33e371/evaluation/evaluation_ex.py)), and DABstep scores the final answer by a quasi-exact match ([the paper](https://arxiv.org/abs/2506.23719)).

In the shop, `gq-001` asks for net revenue in fiscal year 2026. Its golden SQL sums `net_revenue_eur` over `fct_orders`, joined to `dim_date` for the fiscal year. Its check query, which [the section on checking the gold](#check-the-gold) uses, sums `net_amount_eur` over `fct_order_lines` with a date range instead. The example compares the check query with the golden SQL, along with a third query: the golden SQL with its filter on cancelled orders removed. For each, it asks whether the text is equal, whether the text is equal after sqlglot parses and normalizes both, and whether the results match under `results_match()`.

[Example: results-match-rules](../examples/results-match-rules.py)

The query over order lines returns {{out:results-match-rules:by lines}}. Its text differs from the golden SQL even after normalizing, since it reads a different table, and its result matches: `{{out:results-match-rules:by lines results match}}`. The two totals differ by under a euro, because each line is rounded to the cent separately, and the tolerance absorbs that. The query that forgets cancelled orders returns {{out:results-match-rules:forgets cancelled}}, and its result doesn't match: `{{out:results-match-rules:forgets cancelled results match}}`. In text, it is one predicate away from the gold. Normalizing doesn't rescue a comparison of text in either direction, because no parser can tell that two different joins give the same sum on this data.

An execution match has its own blind spot. A query can return the right number for the wrong reason on today's data, such as a filter that happens to remove no rows. Checking more questions, and reading the SQL behind surprising matches, is the defence. That's one reason the set has 48 questions and not 5.

**Working rule:** Score an agent by comparing its result with the golden result, never by comparing SQL text, normalized or not. Keep one comparison function for every score you report, so a change in the score is a change in the agent. When a match surprises you, read the agent's SQL, because a result can match by coincidence.

### Order, rounding and column names {#order-rounding-names}

A [comparison of results](#compare-results-not-sql) still needs rules for the ways two correct results differ. Rows come back in any order unless the query sorts them. Columns carry whatever names the writer chose, in whatever order. Numbers are rounded differently. A rule that is too strict marks correct answers wrong, and a rule that is too loose lets wrong ones through.

`results_match()`, the comparison every score in this book uses, makes these choices. Rows may come in any order, unless the golden question sets `order_matters`. Column names are ignored, and columns may come in any order: it tries each way of lining up the answer's columns with the golden ones. Extra columns are allowed, such as a month next to a total for that month, but the number of rows must be equal. Numbers must agree within {{out:tolerant-comparison:tolerance}} by default, plus an absolute slack of half a unit in the last place the gold rounds to. For money, rounded to the cent, that's half a cent, the default. The example takes the golden result for `gq-002`, net revenue in each region in March 2026, changes it in the ways real answers differ, and compares each version with the original.

[Example: tolerant-comparison](../examples/tolerant-comparison.py)

Reversed rows, swapped columns and an extra month column all match, and so does rounding to whole euros, which moves a regional total by at most half a euro. Rounding to thousands of euros fails, and so does reporting in thousands of euros: `{{out:tolerant-comparison:in thousands of euros}}`. A person reading a small number under a heading of thousands would understand it, but the comparison can't see the heading. That's deliberate. An agent that changes units without saying so is a risk, so the golden question fixes the unit and the agent must meet it. A missing region fails. For a ranking, such as `gq-039`'s, `order_matters` is set. The example ranks the regions by revenue, and the reversed ranking fails.

The tolerance needs care in both directions. Ratios such as a conversion rate are small numbers, where half a cent of slack is a lot. `gq-033`'s conversion rates run from {{out:tolerant-comparison:gq-033 rates}}, so 0.005 is about 4% of each. Its gold rounds to four places, and its absolute slack is half that last place, {{out:tolerant-comparison:gq-033 absolute slack}}. The example adds 0.004 to every rate. Under `gq-033`'s rule the near miss fails, `{{out:tolerant-comparison:rates 0.004 higher, gq-033's rule}}`, and with half a cent of slack it would match, `{{out:tolerant-comparison:rates 0.004 higher, half a cent of slack}}`. The book's other ratios, `gq-031` and `gq-034`, follow the same rule.

**Working rule:** Ignore row order, column order and column names, allow extra columns, and require the same number of rows and numbers within a small relative tolerance. Round each gold to a stated place, and allow half a unit in that place on top. Set `order_matters` only when the question asks for a ranking or a sequence. Fix units and scale in the question or its note, and treat an answer in other units as wrong, because nobody reading it can tell.

## Check the gold before you trust it {#check-the-gold}

[Public benchmarks](#benchmarks-are-not-your-test) show what happens to unchecked gold: about half of one set was wrong. A golden question written in an afternoon is no different. Its SQL can miss a filter, read the wrong table or follow a definition nobody owns, and every score built on it inherits the mistake. So check each gold before it scores anything. It must run. It must return rows, without NULL values, since an empty gold matches any query that also returns nothing. Where you can, a second query written another way, its `check_sql`, must return the same result. And its note must name the definition it follows, so a person can say whether it's the right one.

The example applies those checks to the shop's set. Each check query is written independently of its golden SQL: from order lines instead of orders, from a date range instead of the fiscal calendar, or by counting another way. The example then looks at one question in two readings: which country is top for refunds in fiscal 2026, by the number of refunds and by refund rate.

[Example: gold-runs-and-agrees](../examples/gold-runs-and-agrees.py)

The answerable golden queries all run ({{out:gold-runs-and-agrees:golden SQL that runs}}), {{out:gold-runs-and-agrees:empty or NULL results}} return an empty or NULL result, and {{out:gold-runs-and-agrees:questions with a check query}} questions carry a check query. The check queries agree with their gold in {{out:gold-runs-and-agrees:checks that agree}} cases. The two readings of the refund question disagree, the same trap as DABstep's task 49. The country with the most refunds is {{out:gold-runs-and-agrees:top country by number of refunds}}. The country with the highest refund rate is {{out:gold-runs-and-agrees:top country by refund rate}}. The golden question `gq-028` says "highest refund rate" in its text, and its note defines the rate as refunded euros over gross revenue of the same orders. Without both, an agent that answered the other reading would be scored wrong for answering a question nobody wrote down.

The checks above find gold that is broken. Reading the agent's wrong answers finds gold that is unclear. `gq-031` first asked about the average number of "items" in an order, and [the schema-only baseline from chapter 1](#ask-for-sql) got it wrong: its SQL averaged `line_count`, the number of order lines, where the gold sums units. "Items" allows both readings. The defect was in the question, not the agent, so the question now asks for units, counting quantities, not order lines. Recorded replies are keyed by the exact question text, so the reworded question needed a new recording. The example replays both.

[Example: reworded-golden-question](../examples/reworded-golden-question.py)

Asked about items, the baseline returned {{out:reworded-golden-question:baseline answer, items wording}} against a gold of {{out:reworded-golden-question:gq-031 golden}}. Asked about units, it returned {{out:reworded-golden-question:baseline answer, units wording}}, which is `{{out:reworded-golden-question:baseline outcome, units wording}}`. Its SQL still keeps cancelled orders and takes the year from the UTC timestamp, and on this data neither moves the average past the tolerance. That's [the blind spot of an execution match](#compare-results-not-sql): the answer is right, and the query isn't.

At a larger scale, a model can propose suspect golds for a person to check. The extended version of the CIDR audit describes an agent built for this, which flagged erroneous BIRD Mini-Dev examples with 83% precision ([Jin et al., arXiv:2601.08778](https://arxiv.org/abs/2601.08778)). A person still decides each one.

**Working rule:** Before a golden question scores anything, run its SQL, reject empty and NULL results, compare it with an independent query where you can, and have the definition's owner read its note. Read the agent's wrong answers for unclear questions, and fix the question, not the score. When a question can be read two ways, name the reading in its text, or make it a decline.

## Cover declines and roles, not only answers {#cover-declines-and-roles}

A [checked gold](#check-the-gold) makes each question trustworthy, and the set as a whole still has to test what the agent will meet. A set of answerable questions alone rewards an agent that answers everything: it can never lose points by guessing. So the shop's set includes questions whose right answer is a decline, of two types, because the right behaviour differs. An ambiguous question, such as "Who are our best customers?", has several reasonable answers, and the agent should say which choices it needs. An unanswerable question, such as the cost of shipping, asks for data the warehouse doesn't hold, and the agent should say so. A forbidden question is answerable, but not for the role asking: the shop's finance team may not see customers' emails, and a regional lead may see only their own region. Chapter 8 builds declining and chapter 9 builds access rules. This chapter makes sure the set can score both.

Coverage also means the warehouse's traps and the shop's roles. Every trap built into the shop's warehouse, from test orders to the legacy mart, should appear in both splits, so a change that breaks one trap shows up in either score. The example counts kinds, roles and traps per split.

[Example: golden-coverage](../examples/golden-coverage.py)

Kinds are balanced: each split has the same number of answers, declines and forbidden questions. Every trap appears in both splits, and the last line reads `traps missing from a split: {{out:golden-coverage:traps missing from a split}}`. Several traps rest on one question in a split, such as VAT in the test split, so a single missing tag would take a trap out of a split, and this line would name it.

Roles are not balanced. The dev split's answerable questions are asked by the analyst, finance and one regional lead. Marketing and support ask answerable questions only in the test split. Since prompts and context are tuned on dev, no tuning will see a marketing question the agent should answer, and the first time one is scored is on the held-out set. We keep the imbalance visible rather than move questions between splits after seeing scores, and the next questions written for those two roles go to dev.

**Working rule:** Include declines and forbidden questions from the start, and split declines into ambiguous and unanswerable, because the right answer differs. Tag each question with the traps it tests, and count kinds, roles and traps per split before you score anything. Fix a gap by writing new questions, not by moving existing ones between splits after you've seen how the agent does on them.

## Hold out a test split {#hold-out-a-test-split}

A [set that covers the right things](#cover-declines-and-roles) can still mislead, through the way it's used. Every time you change a prompt because a question failed, you fit the agent a little more closely to those questions. After enough changes, the score on them measures how well you tuned, not how well the agent works. A held-out split is the usual defence: tune on one part, and score the other only when you report a result. A benchmark's hidden test set reduces the risk that its answers leak into training ([the DABstep paper](https://arxiv.org/abs/2506.23719)), but it doesn't stop people from tuning to the style of its questions. Your own held-out split has to be protected by how you work.

The shop's set has {{out:golden-coverage:dev questions}} `dev` questions, which every chapter may tune on, and {{out:golden-coverage:test questions}} `test` questions, which a chapter scores only for the number it reports. The example scores [the schema-only baseline from chapter 1](#ask-for-sql) on both splits. It's the number every later chapter has to beat.

[Example: baseline-on-both-splits](../examples/baseline-on-both-splits.py)

Schema-only SQL gets {{out:baseline-on-both-splits:dev correct}} dev questions right and {{out:baseline-on-both-splits:test correct}} test questions, an accuracy of {{out:baseline-on-both-splits:dev accuracy}} on dev and {{out:baseline-on-both-splits:test accuracy}} on test. On dev, {{out:baseline-on-both-splits:dev error}} queries fail to run and {{out:baseline-on-both-splits:dev wrong}} return a wrong result or answer what should be declined; on test, the counts are {{out:baseline-on-both-splits:test error}} and {{out:baseline-on-both-splits:test wrong}}. It declines nothing, because it can only write SQL. Across both splits it gets {{out:baseline-on-both-splits:decline correct, both splits}} declines right, {{out:baseline-on-both-splits:forbidden correct, both splits}} forbidden questions and {{out:baseline-on-both-splits:answer correct, both splits}} answerable ones.

The two splits differ here by one question, and nothing has been tuned on either yet. Expect them to drift apart once chapters start changing the context on dev. A dev score that climbs while the test score doesn't is the signal that the changes fit the dev questions rather than the shop. With {{out:golden-coverage:dev questions}} questions per split, one question is about four points of accuracy, so treat a difference of one or two questions as noise, and compare the same questions before and after a change rather than two totals.

**Working rule:** Split your golden questions once, before you tune anything, and tune only on dev. Score the test split only when you report a result, and report both splits side by side. When the test questions have been looked at so often that people tune to them, write new test questions and retire the old ones to dev.

## What goes wrong in production {#golden-questions-in-production}

The shop's 48 golden questions measure the agent in this book. The same practice on a real warehouse fails in these ways, and each has a way to notice.

**The gold goes stale when a definition changes.** If finance changes the definition of net revenue, every golden query that sums `net_revenue_eur` may be wrong without failing. Keep the golden questions in the same repository as the definitions and the metrics, review changes to them together, and re-run the check queries on every change. A check query that stops agreeing is the alarm.

**Golden results move as data arrives.** Refunds keep arriving for months after an order, so `gq-018`'s refunds on March 2026 orders grow every time the refunds table loads. Golden questions over open periods give a different golden result each week, and a comparison that stored last week's result fails for no reason. Compute golden results from golden SQL at scoring time, as `golden_result()` does, and prefer closed periods for questions where the number must stay put.

**The set stops looking like the questions people ask.** Questions change with the business: a new channel, a new region, a new fiscal policy. A set written once drifts away from them. Sample questions from what people ask the agent, write golden questions for those it got wrong or declined, and add them to dev.

**The test split leaks.** Someone reads the failing test questions and tunes the prompt to them, and the test score rises with nothing else improving. You notice when dev and test scores move together after a change aimed at one question. Keep the test questions out of tuning discussions, and refresh them when they have leaked.

**A benchmark score moves with the benchmark.** A vendor's accuracy on BIRD or Spider describes one version of a set that its maintainers correct. When comparing models, record the version of the benchmark with every score, and re-score on your own set before you switch.

**The comparison hides a change of units.** An agent that starts returning revenue in thousands of euros fails every money question at once, and a looser tolerance would hide it. Keep the tolerance small and relative, and when many questions fail together, read one answer before you touch the rule.

**Working rule:** Treat the golden set as code: keep it beside the definitions, run its checks in CI, compute golden results at scoring time, add questions from real traffic to dev, and protect the test split. When a score moves, read the answers that changed before you change the set or the comparison.

## Decisions this chapter made {#golden-questions-decisions}

- **The main evaluation set is the shop's own:** 48 golden questions written from the work a shop's teams do, with roles, kinds and definitions, in `examples/data/golden/questions.toml`.
- **Public benchmarks are cited, not used for scoring.** BIRD and Spider 2.0 appear only as citations. A three-task subset of DABstep, under CC BY 4.0 and pinned by revision, shows that a public score and a score on your warehouse disagree.
- **DABstep's data travels with its licence.** The subset keeps the dataset's own `LICENSE`, drops four identifier columns, keeps every row and the merchants' fictional names, and `SOURCE.md` states each change.
- **Results are compared, not SQL text,** with one function, `results_match()`, for every score: any row order unless the question asks for one, column names and order ignored, extra columns allowed, numbers within a small relative tolerance plus half a unit in the gold's last rounded place.
- **Every gold is checked before it scores:** it runs, returns rows without NULLs, and agrees with an independent query where one exists. Its note names its definition.
- **Declines and forbidden questions are part of the set:** declines split into ambiguous and unanswerable, and forbidden questions across the shop's roles.
- **The set is split once into dev and test,** 24 each, with kinds balanced. Chapters tune on dev and score test only for the numbers they report.
- **Schema-only SQL is the baseline** on both splits, and every later chapter reports its change against it.
