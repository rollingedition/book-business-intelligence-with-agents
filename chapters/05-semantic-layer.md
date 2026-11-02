---
chapter_id: semantic-layer
---

# Define metrics once in a semantic layer

By the end of this chapter, you can write the shop's semantic models and metrics in MetricFlow's YAML spec, compile a metric request to SQL with the book's own compiler, show that its entity joins can't fan out, group by the fiscal calendar, and confirm that MetricFlow compiles the same definitions to the same results.

Chapter 1 answered one question from one defined metric, net revenue, written as a few lines of Python with its SQL built by string formatting. That was enough to show the shape the book keeps: the model chooses a governed definition, and code writes the SQL. It isn't enough for the questions the shop's teams ask. Finance wants refund rates by country in fiscal 2026. A category manager wants net revenue by product category, which lives on the order lines, not the orders. Marketing wants average order value by channel. Each of those needs a join, a grain or a ratio, and each is a place where [chapter 2](#wrong-numbers) found schema-only SQL going wrong: a join that repeats rows, a definition the schema doesn't hold, a year that doesn't start in January.

A semantic layer is where those choices are written down once. It describes each table by its entities (the keys it can be joined on), its dimensions (what you can group and filter by) and its metrics (the numbers people ask for, with their rules), and it compiles a request for a metric into SQL. The evidence that business meaning in a model's context helps is thin. The one benchmark we rely on, over one enterprise insurance schema, found that GPT-4 answered 16% of questions correctly over the SQL tables and 54% over a knowledge-graph layer that carried the business's meaning ([Sequeda et al., 2023](https://arxiv.org/abs/2311.07509)). The authors work for a knowledge-graph vendor, and the study covers one schema and one model, so read it as a sign that meaning helps, not as a multiplier you will see.

This chapter builds the shop's semantic layer in MetricFlow's YAML, compiles it with a small compiler of the book's own, `lib/semantic.py`, and checks it against MetricFlow {{version:metricflow}}, which reads the same files. MetricFlow is the semantic layer dbt Labs maintains, available under the Apache 2.0 licence since Oct 14, 2025, from version 0.209.0 on ([dbt Labs](https://www.getdbt.com/blog/open-source-metricflow-governed-metrics); [PyPI](https://pypi.org/project/metricflow/0.213.0/)). The book uses its own compiler so that you can read every step from request to SQL, and so that the examples change only when we change them.

## Describe each table as a semantic model {#entities-measures-dimensions}

A semantic model is one table described for the layer: which table it reads, the entities it holds, the dimensions it offers and the time dimension its numbers are counted on. An entity is a key with a type. A primary entity is unique in its table, so other tables can join to it many rows to one. A foreign entity is a key that points at another table's primary entity, and it repeats. That one word, primary or foreign, is what lets a layer join tables without repeating rows, so it is the most important thing you declare. The shop's whole layer lives in `examples/data/semantic/`: one file per semantic model, one `metrics.yml`, and one `project_configuration.yml`, which names the time spine, a table with one row per day.

Older MetricFlow specs have a third kind of element, the measure: an aggregation declared on the semantic model, which a metric then names. dbt's documentation for its spec in dbt v1.12 and later says "Measures are deprecated in the new spec and are replaced with simple metrics" ([dbt Labs](https://docs.getdbt.com/docs/build/latest-metrics-spec)). The shop's YAML follows that direction. Each simple metric names its semantic model, its aggregation and its expression itself, in the standalone document shape that MetricFlow's own parser reads: one `semantic_model:` or `metric:` per YAML document, and tables named by `node_relation`. Here is the shop's orders model, shortened, and net revenue, the metric chapter 1 defined in Python:

```yaml
semantic_model:
  name: orders
  node_relation:
    schema_name: analytics
    alias: fct_orders
  defaults:
    agg_time_dimension: order_date
  entities:
    - name: order
      type: primary
      expr: order_id
    - name: customer
      type: foreign
      expr: customer_id
  dimensions:
    - name: order_date
      type: time
      expr: order_date_local
      type_params:
        time_granularity: day
    - name: region
      type: categorical
---
metric:
  name: net_revenue
  type: simple
  type_params:
    expr: net_revenue_eur
    metric_aggregation_params:
      semantic_model: orders
      agg: sum
  filter: "{{ Dimension('order__status') }} != 'cancelled'"
```

The orders model's time dimension is `order_date_local`, the order's local business day, so every metric on it counts days the way finance does. Net revenue's rule for which orders count, the one chapter 1's schema-only SQL missed, is the metric's `filter`. `metrics.yml` also holds net revenue's description, word for word as chapter 1 wrote it, and chapter 1's `lib/metrics.py` reads its table, aggregate and condition from this YAML, so the definition exists in one place.

The first example loads the layer, lists what each semantic model declares, and checks the definitions against the warehouse: every expression must run, and every primary entity must be unique in its table. Then it checks a copy with one mistake, in which the order lines declare `order` as their primary entity.

[Example: load-semantic-models](../examples/load-semantic-models.py)

The shop has {{out:load-semantic-models:semantic models}} semantic models and {{out:load-semantic-models:metrics}} metrics, and the check finds {{out:load-semantic-models:problems in the shop's definitions}} problems in them. The mistaken copy fails it: `{{out:load-semantic-models:problem}}`. An order has several lines, so `order_id` repeats in the lines table, and a layer that believed it unique would join orders to lines as if each order had one line. Parsing the YAML can't find this, because the file is valid. Only the data can, which is why `check()` counts duplicates. Two of the semantic models, and the time spine, read views in a third schema of the warehouse, `semantic`, which this chapter adds; the [fiscal calendar section](#time-grains-and-fiscal) and the [production section](#semantic-layer-in-production) say why.

**Working rule:** Declare one semantic model per table, mark an entity primary only where it's unique, and check the declarations against the data whenever the warehouse or the YAML changes. Write simple metrics without measures, naming their model and aggregation, unless your MetricFlow version or your dbt project still requires measures.

## Compile a metric request to SQL {#compile-a-metric-request}

With the [shop's definitions loaded](#entities-measures-dimensions), the layer's job is to turn a request into SQL. A metric request names the metrics, the dimensions to group by and the filters, and optionally an order and a limit. It holds names, not SQL, so everything in it can be checked against the definitions before anything runs. The compiler then finds each dimension's column, adds the joins and the metric's own filter, and writes the aggregate.

The book's compiler builds the query as a sqlglot expression tree rather than as text. sqlglot is a Python library that parses, builds and translates SQL. Building a tree has two consequences. A filter value becomes a literal node in the tree, so text inside it can't change the query's structure. And the same tree can be written in another warehouse's dialect, which the [dialect subsection](#any-dialect) uses.

Dimension names follow MetricFlow's convention, so a request reads the same in either tool:

| Name | What it reaches |
| --- | --- |
| `order__region` | `region` in the model whose primary entity is `order` |
| `order__customer__region` | `region` of the order's customer, two joins away |
| `metric_time__month` | the metric's own time dimension, by month |
| `metric_time__fiscal_quarter` | a fiscal quarter from the time spine, a custom grain ([fiscal section](#time-grains-and-fiscal)) |

The example answers chapter 1's question, golden question `gq-002`: "What was net revenue in each region in March 2026?" The example asks for `net_revenue` grouped by `order__region` and filtered to March 2026, prints the request and the SQL, runs it, and compares the answer with the golden result. Then it sends a filter value that holds SQL of its own, and a request for a dimension the layer doesn't define.

[Example: compile-net-revenue](../examples/compile-net-revenue.py)

The SQL reads one table, `analytics.fct_orders`, applies the metric's filter on cancelled orders, truncates the local business day to its month and groups by region. It's what an analytics engineer would write by hand, and it matches the golden result: `matches golden: {{out:compile-net-revenue:matches golden}}`. The month is written as a date and compared with a date cast, so the comparison doesn't depend on how a warehouse compares text.

The hostile value doesn't change the query. It compiles to `{{out:compile-net-revenue:hostile filter compiles to}}`: one string literal, its quotes doubled, compared with `orders.region`. No region has that name, so the query returns one row with an empty total. Chapter 1's metric passed values as query parameters for the same reason; a tree of literals does the same job and still lets the query be translated to another dialect.

What a request can't name matters as much. A request for a metric or dimension that isn't defined fails before any SQL exists. The example's request for `order__colour` ends in a `SemanticError` that names the unknown dimension and lists every dimension net revenue can use, from `metric_time__day` to `order__status`. That error is what an agent sees when it asks for something the layer doesn't hold, and [chapter 6](#metrics-first) builds on it.

**Working rule:** Let the agent, and every other client, send metric requests, never SQL fragments. Resolve every name in a request against the definitions, build the query as a tree with values as literals, and show the SQL with every answer so a person can read what ran. Accept a raw SQL filter only from the people who maintain the layer, never from a model.

## Join through entities so sums can't fan out {#join-through-entities}

The [compiled request](#compile-a-metric-request) read one table. Many questions need two. A fan-out happens when a join matches each row of one table to several rows of another, so a sum over the joined rows counts each value of the first table several times. A semantic layer prevents it with the entity types: it joins from a metric's table only to a table where the entity is primary, many rows to one, so each row of the metric's table matches at most one row. MetricFlow's documentation lists a join from a primary to a foreign entity as "Fan-out (Not allowed)" and allows at most two hops ([dbt Labs](https://docs.getdbt.com/docs/build/join-logic)). The book's compiler applies the same two rules.

The shop's case is a category manager's question: net revenue by product category in 2025. Net revenue is summed per order, in `analytics.fct_orders`, and a product's category is reached through the order lines, several per order. The example asks the layer for `net_revenue` by `product__category`, runs the hand-written join a model would write, and then asks for the line-level metric instead.

[Example: entity-join-no-fanout](../examples/entity-join-no-fanout.py)

The layer refuses the request and says why: `{{out:entity-join-no-fanout:refused}}`. The hand-written join shows what the refusal prevents. Net revenue in 2025 is {{out:entity-join-no-fanout:net revenue, 2025}} euros. Summed over the orders joined to their lines, the same revenue comes to {{out:entity-join-no-fanout:summed over the joined lines}}, inflated by {{out:entity-join-no-fanout:inflated by}}, because each order counts once for each of its lines. Nothing in that query fails, and nothing in its result says it's wrong.

`line_net_revenue` is net revenue counted on the lines themselves, in the `order_lines` semantic model, with the same rule on cancelled orders. Its SQL joins the lines to products and to orders, both many rows to one, so no line repeats. The categories add up to {{out:entity-join-no-fanout:categories add up to}} euros, {{out:entity-join-no-fanout:difference from net revenue}} away from net revenue. That gap is rounding, not fan-out: the warehouse rounds each line's amount and each order's total to the cent separately, and over a year of lines the cents add up.

When a request needs numbers from two tables, a layer doesn't join the tables first. It aggregates each metric in its own table, then joins the aggregated results on the dimensions they share; MetricFlow uses full outer joins for that step ([dbt Labs](https://docs.getdbt.com/docs/build/join-logic)), and so does the book's compiler. Each sum is complete before any join, so no join can repeat its rows.

The protection holds only as far as the declarations are true. Declare the lines' `order` entity primary, as the [loading example](#entities-measures-dimensions) did on purpose, and the layer would join orders to lines without complaint.

**Working rule:** Declare entities so that every join the layer makes is many rows to one, and let the layer refuse the rest. When a question needs a number on a finer table, such as revenue by product, define the metric on that table rather than reaching it through a join. Check that primary entities are unique in the data, because a wrong declaration turns the protection off.

## Build ratio and derived metrics from simple ones {#ratio-and-derived-metrics}

Simple metrics, like the [line-level revenue](#join-through-entities), aggregate one column of one table. Many of the numbers people ask for are built from two: a refund rate, an average order value. A ratio metric divides one metric by another, and a derived metric combines several with an expression. What matters is the order of operations: a ratio is the sum of the numerator over the sum of the denominator, per group, never the average of row-by-row ratios. MetricFlow computes the numerator and the denominator in separate subqueries, joins them on their common dimensions and then divides ([dbt Labs](https://docs.getdbt.com/docs/build/ratio)).

The shop's finance team defines the refund rate in golden question `gq-028`: refunded euros over gross revenue of the same orders, those placed in the period that weren't cancelled. Two choices hide in that sentence. The refunds belong to the order's day, not the day the money went back, so the numerator is `order_refunds`, a metric counted on the order's local day; `refunds`, counted on the day of the refund, answers a different question. And the denominator is gross revenue, not net revenue. A refund pays back what the customer was charged, tax included, and gross revenue includes tax while net revenue leaves it out, so only gross revenue measures both sides in the same euros; over net revenue, a fully refunded order would have a refund rate above 100%. The book uses this one definition everywhere, in the glossary and the verified queries as well. The numerator carries the rule on cancelled orders as an input filter, and `gross_revenue` carries it in its own definition, so each side applies it.

The example compiles the refund rate by region for fiscal 2026 and prints its SQL. Then it computes the tempting version, each order's refunds over its gross revenue averaged per region, and checks two golden questions: the country with the highest refund rate, and average order value by region in March 2026.

[Example: refund-rate-metric](../examples/refund-rate-metric.py)

The SQL has one part per input. `order_refunds` sums refunds joined to their orders, filtered and dated by the order, and `gross_revenue` sums the orders. The outer query joins the two on region and divides, with `NULLIF` so that a region with no revenue gets no rate instead of an error. EMEA's refund rate is {{out:refund-rate-metric:refund rate, EMEA}}, AMER's {{out:refund-rate-metric:refund rate, AMER}} and APAC's {{out:refund-rate-metric:refund rate, APAC}}.

The average of per-order rates gives other numbers: {{out:refund-rate-metric:average of per-order rates, AMER}} for AMER against the layer's {{out:refund-rate-metric:refund rate, AMER}}, and {{out:refund-rate-metric:average of per-order rates, EMEA}} for EMEA against {{out:refund-rate-metric:refund rate, EMEA}}. It weights a small order's refund as heavily as a large one's, so it answers what share of a typical order is refunded, which nobody asked. Here it moves AMER and APAC up and EMEA down, so the regions look closer together than the money says they are.

The highest refund rate by country is {{out:refund-rate-metric:highest refund rate}}, which matches the golden answer: `{{out:refund-rate-metric:gq-028 matches golden}}`. Average order value is a derived metric, `net_revenue / kept_orders`, where `kept_orders` is the `orders` metric with the rule on cancelled orders applied as an input filter. The shop counts orders with cancelled ones included, but divides revenue by orders without them, and the derived metric keeps both definitions. It matches golden question `gq-009`: `{{out:refund-rate-metric:gq-009 matches golden}}`.

**Working rule:** Define every rate as a ratio of two metrics, so each side is aggregated on its own and divided per group. Write down which time dimension each side is counted on, and make sure each side applies its filter, in its own definition or as an input filter, rather than relying on readers to know. Use a derived metric when the expression is more than one division, and keep its inputs simple metrics you can query on their own.

## Put the fiscal calendar in the time spine {#time-grains-and-fiscal}

Every metric in the [shop's layer](#entities-measures-dimensions) is counted on a time dimension, and most questions name a period. A layer handles standard grains, such as month, quarter and year, by truncating the date. Fiscal periods can't be computed that way, because they start where the business says they do. MetricFlow handles both through the time spine, a table with one row per day that every time-based metric needs, at least at a daily grain. A custom granularity, such as `fiscal_year`, is a column of the time spine that names the period each day belongs to ([dbt Labs](https://docs.getdbt.com/docs/build/metricflow-time-spine)).

The shop's fiscal year starts on February 1 and is named for the year it ends in, so fiscal 2026 runs from February 1, 2025 to January 31, 2026. The warehouse's `analytics.dim_date` holds `fiscal_year` and `fiscal_quarter`, but its quarter is a number from 1 to 4, which repeats every year. A custom grain must name one period, so the view `semantic.calendar` labels each quarter with its year, as in `2026-Q1`, and the project configuration declares `fiscal_year` and `fiscal_quarter` as custom grains of that view. A request then groups by `metric_time__fiscal_quarter` like any other grain.

The example groups net revenue by fiscal quarter in fiscal 2026 and prints the SQL, groups it by calendar quarter in 2025 to show the difference, and checks two golden questions about first fiscal quarters.

[Example: fiscal-quarter-grain](../examples/fiscal-quarter-grain.py)

The fiscal request joins the orders to `semantic.calendar` on the local business day and groups by the calendar's quarter label. The calendar quarters of 2025 start on January 1, April 1, July 1 and October 1, while fiscal 2026's first quarter runs from February to April 2025, so no quarter in one grouping equals a quarter in the other. Fiscal 2026's first quarter, February to April 2025, brought {{out:fiscal-quarter-grain:fiscal 2026-Q1, February to April 2025}} euros of net revenue; the calendar's first quarter of 2025, January to March, brought {{out:fiscal-quarter-grain:calendar 2025 Q1, January to March 2025}}. Both golden questions match: net revenue in the first quarter of fiscal 2026, `gq-010` (`{{out:fiscal-quarter-grain:gq-010 matches golden}}`), and by region in the first quarter of fiscal 2027, `gq-026` (`{{out:fiscal-quarter-grain:gq-026 matches golden}}`).

Two limits apply. MetricFlow "doesn't perform any timezone manipulation" ([dbt Labs](https://docs.getdbt.com/docs/build/metricflow-time-spine)), so the local business day has to exist in the warehouse before the layer sees it. The shop's marts build `order_date_local` from each region's time zone, and the views add the same for refunds. And the same documentation marks custom calendars as a preview feature, without offsets or period-over-period comparisons at custom grains, so "fiscal Q1 against the same quarter last year" takes two requests, not one.

**Working rule:** Put every fiscal and business calendar in the time spine as custom grains whose values each name one period, and let requests group by them. Build local business days in the marts, before the layer. When you need a comparison across fiscal periods, run one request per period and compare the results in code, until your layer supports offsets at custom grains.

## Check the definitions against MetricFlow {#check-against-metricflow}

The [shop's YAML](#entities-measures-dimensions) is portable only if a production tool reads it the way the book's compiler does. In production, MetricFlow usually runs inside a dbt project, through the `dbt-metricflow` package and its command line. That package's summary reads "Execute commands against the MetricFlow semantic layer with dbt", and it requires `dbt-core` ([PyPI](https://pypi.org/project/dbt-metricflow/0.15.0/)). The book checks its definitions with MetricFlow alone, the `metricflow` package, which is Apache 2.0 and has no dbt dependency, so the check runs offline in seconds without installing dbt and its dependencies. MetricFlow parses and validates the same files, and its engine's `explain()` returns the SQL it would run. Its Python engine, `MetricFlowEngine`, is internal API at a 0.x version: the class's docstring, in `metricflow/engine/metricflow_engine.py` of the 0.213.0 wheel ([PyPI](https://pypi.org/project/metricflow/0.213.0/#files)), leaves its maintainers a note to "provide a more stable API layer instead of assuming this class is stable". The book keeps everything that touches it in `lib/metricflow_bridge.py`, with a small adapter that lets MetricFlow run SQL on DuckDB.

The example compiles {{out:metricflow-agrees:requests compared}} requests both ways, covering simple, ratio and derived metrics, a two-hop join, the fiscal grains and two time dimensions on one table, runs both statements on the shop's warehouse and compares the rows. It prints MetricFlow's SQL for chapter 1's question, then sends MetricFlow the request the [join section](#join-through-entities) refused.

[Example: metricflow-agrees](../examples/metricflow-agrees.py)

All {{out:metricflow-agrees:requests that agree}} requests return the same rows. The one difference the comparison has to allow is a type: MetricFlow returns a month as a `{{out:metricflow-agrees:MetricFlow's type for metric_time__month}}`, a timestamp at midnight, while the book's compiler casts it to a `{{out:metricflow-agrees:the book's type for metric_time__month}}`, so the example turns timestamps into dates before it compares. MetricFlow's SQL is longer, with a comment naming each step, and it reaches the same three regional totals. It refuses net revenue by product category in 2025 too, with an `{{out:metricflow-agrees:MetricFlow on net_revenue by product__category}}`. Among the common issues its message lists is the one the join section met: "{{out:metricflow-agrees:one cause MetricFlow lists}}"

MetricFlow also asks more of the YAML than the book's compiler does: every semantic model that a simple metric counts on needs a time dimension of its own. The next example builds MetricFlow's engine from the shop's YAML, then from a copy that points `order_lines` at `analytics.fct_order_lines`, the analytics table, which has no order day, and drops the model's time dimension.

[Example: metricflow-needs-a-date](../examples/metricflow-needs-a-date.py)

The shop's YAML builds a `{{out:metricflow-needs-a-date:MetricFlow with the shop's YAML}}`. The copy doesn't: MetricFlow raises an `{{out:metricflow-needs-a-date:MetricFlow without a date on order_lines}}` whose message begins "{{out:metricflow-needs-a-date:its message begins}}". That is why the shop's `order_lines` model reads the view `semantic.order_lines`, which adds each order's local day.

**Working rule:** Compare your layer with MetricFlow, or whichever tool serves it in production, on every request shape you rely on, and run the comparison whenever either side changes. Pin MetricFlow's version exactly and keep its engine behind one module, because its Python API can change in any release.

### One definition, any warehouse's dialect {#any-dialect}

A layer that compiles to an expression tree, as [the book's compiler does](#compile-a-metric-request), can write that tree for another warehouse. sqlglot {{version:sqlglot}} calls itself "a transpiler, not a validator", warns that some queries can't be translated between some dialects, and by default makes a best-effort translation unless `unsupported_level` is set to raise ([PyPI](https://pypi.org/project/sqlglot/30.27.0/)). The example writes the refund rate by calendar quarter in six dialects and prints the two lines that differ: the quarter and the division. It also prints BigQuery's quarter as sqlglot writes it from an uncast column.

[Example: transpile-metric-sql](../examples/transpile-metric-sql.py)

The compiler casts the time column to a date before it truncates, and that cast decides BigQuery's line. Without it, sqlglot writes `{{out:transpile-metric-sql:bigquery without the cast}}`, and BigQuery documents `TIMESTAMP_TRUNC`'s argument as a timestamp or a datetime, not a date ([Google Cloud](https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/timestamp_functions)). With it, BigQuery gets `DATE_TRUNC`, which takes a date and a `QUARTER` granularity ([Google Cloud](https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/date_functions)), and Databricks gets `TRUNC`. The division gains a cast to a floating-point type for Postgres and T-SQL, so a ratio of integers stays fractional there; DuckDB's division operator is already float division ([DuckDB](https://duckdb.org/docs/2.0/sql/functions/numeric.html)).

The output shows two limits. The same cast changes T-SQL: its quarter line reads `DATE_TRUNC`, while Microsoft documents T-SQL's function as `DATETRUNC`, with no underscore ([Microsoft](https://learn.microsoft.com/en-us/sql/t-sql/functions/datetrunc-transact-sql)). The fix for one dialect may have broken another, and sqlglot raised nothing, though the example sets `unsupported_level=ErrorLevel.RAISE` for every dialect. And the last line, `ILIKE`, passes through to T-SQL unchanged even with `unsupported_level=ErrorLevel.RAISE`, though T-SQL's pattern match is `LIKE`, with no `ILIKE` ([Microsoft](https://learn.microsoft.com/en-us/sql/t-sql/language-elements/like-transact-sql)). We couldn't run BigQuery or SQL Server here. A query that transpiled is a query you still have to run on the target warehouse.

**Working rule:** Keep one definition and transpile it, but treat each dialect's SQL as untested until it runs on that warehouse against a known answer. Cast dates and divisions explicitly in the compiler, so the translation has less to guess.

## What goes wrong in production {#semantic-layer-in-production}

The shop's layer answers the shop's golden questions. A layer over a real warehouse fails in these ways, and each has a way to notice.

**A wrong entity type turns off the fan-out protection.** A foreign key declared primary makes the layer join many rows as if they were one, and every sum through that join inflates. Parsing won't catch it. Count duplicates of every primary entity in the data, as `check()` does, in CI and after every load.

**A fact without its own date can't carry a metric.** MetricFlow wants a time dimension in the same semantic model as each simple metric, and at {{version:metricflow}} it refuses to build its engine without one, as the [MetricFlow section](#check-against-metricflow) shows with an `{{out:metricflow-needs-a-date:MetricFlow without a date on order_lines}}`. The shop's order lines had no date, which we found while writing this layer. That is why the warehouse adds `semantic.order_lines` with each order's local day. Put the business date on every fact table in the marts.

**Two definitions of one metric drift apart.** A metric defined in the layer and again in a dashboard, a notebook or an agent's prompt disagrees after the first change to one of them. Chapter 1's metric reads its definition from the YAML for that reason. Search for each metric's columns outside the layer, and run the golden questions after every change to the YAML.

**Filters are templates, and templates are code.** A metric's `filter` is a Jinja template, and MetricFlow's changelog records sandboxing their rendering to fix a security issue ([dbt Labs](https://github.com/dbt-labs/metricflow/blob/main/CHANGELOG.md)). Never pass a filter string written by a model or a user to a layer. Send structured filters, as `lib/semantic.py`'s `MetricRequest` does, and keep templates for the people who maintain the YAML. [Chapter 9](#who-may-see-what) attaches row filters at this point.

**The engine's API moves.** MetricFlow's Python engine is internal, at a 0.x version, and a release can rename an argument or change the SQL's shape. Keep every call in one module, pin the version exactly, and let the comparison with your own compiler, or with golden results, tell you when an upgrade changed a number.

**Formats move too.** dbt's spec for dbt v1.12 and later moves entities and dimensions under columns and replaces measures with simple metrics ([dbt Labs](https://docs.getdbt.com/docs/build/latest-metrics-spec)), and Apache Ossie, the former Open Semantic Interchange, is another format that MetricFlow ships converters for ([Apache Ossie](https://ossie.apache.org/updates/ossie-enters-apache-incubator/); [dbt Labs](https://github.com/dbt-labs/metricflow/blob/main/CHANGELOG.md)). Pick one format, keep it in version control, and convert with a tool you test, never by hand.

**Working rule:** Treat the semantic layer as code with tests: check entity uniqueness against the data, run every metric's SQL in CI, compare against MetricFlow and the golden questions on every change, and accept only structured requests from anything that isn't a person who maintains the layer.

## Decisions this chapter made {#semantic-layer-decisions}

- **The shop's metrics live in one place,** `examples/data/semantic/*.yml`, in MetricFlow's standalone YAML: five semantic models, ten metrics and one time spine. Chapter 1's `net_revenue` reads its definition from there.
- **Simple metrics are measure-free:** each names its semantic model, aggregation and expression, the direction dbt's spec takes, and MetricFlow {{version:metricflow}} reads them.
- **The book compiles with its own code,** `lib/semantic.py`, which builds sqlglot expressions, joins only many rows to one, aggregates each input of a ratio or a multi-metric request on its own, and refuses a fan-out with a reason.
- **Requests carry names and values, never SQL,** and filter values become literals in the expression tree.
- **The fiscal calendar is the time spine's custom grains,** `fiscal_year` and `fiscal_quarter`, labelled so each value names one period.
- **The warehouse gains a `semantic` schema** of three views, so every fact has its own date and every fiscal quarter has a name. The `raw` and `analytics` schemas, and every recorded prompt, are unchanged.
- **MetricFlow alone, without dbt, checks the definitions,** through one module, and agrees with the book's compiler on every request the chapter compares. The `metricflow` package is Apache 2.0 and runs offline with no dbt dependency; `dbt-metricflow` is the usual production route.
- **One definition is transpiled per warehouse,** with the time column cast to a date before truncation, and the transpiled SQL is treated as untested until it runs there.
- **Rates are ratios of sums,** each side aggregated on its own with its own filter and time dimension: the refund rate is refunds on the period's orders over their gross revenue, which includes tax as refunds do, and the book's glossary and verified queries use the same definition.
- **Definitions are checked against the data,** not only parsed: every expression runs and every primary entity is unique, so a mis-declared key is caught before it inflates a sum.
