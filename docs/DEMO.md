# Demo script — record this one

**Runs about 4 minutes.** The brief asks for *"a 3–5 minute demo using the GitHub project,
explaining one important FDE judgement call you made"* — so this is built to land in that window,
opens on the GitHub repo, and is organised around a single judgement call rather than a tour.

Simple words throughout. Screen cue in brackets, then what you say.

---

### 1. Open on the repo · ~15 sec

**[GitHub repo page]**

"This is the project on GitHub. Everything I'm about to show you lives in here — the code, the
data, and the write-ups."

### 2. The problem and the sources · ~30 sec

**[Scroll the README]**

"FlashEats had a problem. Deliveries were late, customers didn't trust the arrival time, and they
wanted to buy an AI tool that predicts delays. They asked me to check the data first.

Their data sat in four places — a database, an API, an event file from the driver app, and some
hand-kept spreadsheets. I pulled from all four."

### 3. The judgement call · ~90 sec — *this is the heart of it, don't rush*

**[Open `sources/data/client_metric_definitions.json`]**

"Now, the judgement call.

Before I calculated anything, I went looking for who decides what the word *late* means. This is
what I found. Four people at the company, four different answers. The head of operations says one
second past the promised time is late. The support lead says only past ten minutes counts. Finance
says don't count cancelled orders at all.

And the last line says it plainly — nobody officially owns this."

**[Open `out/dashboard.html`]**

"So I ran all of them.

One second late gives fifty-six percent — exactly the number leadership already uses, so their
maths is fine. The same orders on the ten-minute rule give twenty-three percent.

And the typical late order missed by about a minute and a half. So that fifty-six percent is mostly
orders late by seconds.

**[Point at the curve]**

This chart is every possible answer. Every point on it is a real, defensible late rate. The number
slides from fifty-six down to eight just by moving one setting that nobody owns.

The easy thing was to pick one, put it in the code, and hand over a clean single number. I decided
that was the wrong thing to do. Choosing that line is a business decision, not an engineering one.
If I bury it in code, I hide the most important thing I found."

**[Open `src/flasheats/validate/rules.py`, scroll to `_kpi_definition_owner`]**

"So the pipeline does two things instead. It publishes both numbers side by side, every single run.
And this check here never passes — it is built to always come back *unknown*, and it stays unknown
until a real person picks a definition.

My checks have four results, not two: pass, warn, fail, and unknown. That fourth one lets the
pipeline say *nobody has answered this yet* instead of quietly guessing."

### 4. What that let me find · ~45 sec

**[Dashboard, the bar chart]**

"Because I wasn't stuck arguing about the number, I could look at the journey itself. I rebuilt
every order, step by step, across all four systems.

Finding a driver — not slower on late orders. Slightly faster, actually.

Driving to the customer — about four minutes slower.

But between picking a driver and collecting the food — seventeen minutes slower. That one gap is
eighty-one percent of the problem.

So the tool they wanted to buy would predict the delay more accurately and remove none of it.
Don't buy it yet."

### 5. What I could not prove · ~30 sec

**[Open `ASSUMPTIONS.md`]**

"And here's what I couldn't answer. Inside those seventeen minutes — is the restaurant slow, or is
the driver turning up too early? Those need different fixes.

I don't know. That data covers one order in ten, it's typed by hand, and some of it says the food
was ready *after* it was collected — which can't happen. So I wrote it down as an open question
instead of guessing."

### 6. That it actually runs · ~30 sec

**[Terminal]**

```
make run
```

"One command runs the whole thing. It keeps a copy of every file it pulls, and running it twice
gives the exact same answer.

```
make run CHAOS=stale_data
```

And if I break it on purpose — here, telling it the data is out of date — it stops, says why,
and publishes nothing."

### 7. Close · ~20 sec

"So, the judgement call: they asked for one number. I gave them two, and told them who needs to
choose. That mattered more than the number itself.

Thanks for watching."

---

## Recording notes

- **Open these tabs first:** the GitHub repo page, `client_metric_definitions.json`,
  `out/dashboard.html`, `src/flasheats/validate/rules.py`, and a terminal in the project folder.
- **Run `make run` once before recording** so Docker is warm — otherwise the live run pauses while
  the containers wake up and you lose fifteen seconds of tape.
- **Section 3 is the graded part.** The brief asks for *one* judgement call explained well, not a
  feature tour. If you overrun, cut from section 6, never from section 3.
- **Slow down on fifty-six versus twenty-three.** Let it sit for a beat. That comparison is the
  entire point of the demo.
- Say "I decided" and "I could have, but I didn't" out loud. The brief is marking your reasoning,
  so the decision needs to sound like yours.

---

# Demo script — long version (3 to 5 minutes)

Keep as backup, or for questions afterwards.

The brief asks for one important FDE judgement call, explained using the repository. This is that
call, with the exact commands and the exact things to say.

**The judgement call: the pipeline refuses to publish a single late-delivery rate.**

---

## 0:00 — The escalation (20 s)

> Show `README.md` at the top.

"FlashEats came to us with a specific ask: *late deliveries are increasing, customers say our ETA
is unreliable, figure out what's happening before we invest in an AI delay-prediction system*.
Leadership's working number is **56% late**.

So there are really two questions. Is 56% right? And is an ETA model the fix?"

---

## 0:20 — The judgement call (70 s)

> Open `sources/data/client_metric_definitions.json`.

"Before computing anything I went looking for who owns the definition. This file is what I found.
Four stakeholders, four different definitions of 'late'. VP Operations says any second past the
ETA. The Support Lead says only beyond ten minutes counts. Finance says exclude cancellations. And
the last line says it outright — **no canonical KPI owner is documented**.

> Open `out/dashboard.html`, section 1.

So I computed all of them. Strict gives **56.39%** — that reproduces leadership's number exactly.
The same rows, with the Support Lead's ten-minute rule, give **23.34%**. And the median delay is
**1.4 minutes**, so that 56% is overwhelmingly orders that arrived seconds late.

> Point at the sensitivity curve.

Every point on this curve is a defensible late-delivery rate. The number is a function of a
parameter that nobody owns.

**Here is the judgement call.** The obvious move is to pick one, write it into the transform, and
ship a clean single number. I decided that's the wrong thing to do — picking a threshold is a
policy decision that belongs to VP Operations, and burying it in SQL would hide the most important
finding of the engagement behind a number that looks authoritative.

> Open `src/flasheats/validate/rules.py`, scroll to `_kpi_definition_owner`.

So the pipeline publishes both, each with its denominator, and this rule — `kpi.definition_owner`
— is hard-coded to return **UNKNOWN** on every single run. It can never return PASS until a human
ratifies a definition. The gate has four states, not two, precisely so it can say *this question
isn't answerable yet* instead of quietly guessing."

---

## 1:30 — Then: where the delay actually is (60 s)

> `out/dashboard.html`, section 2.

"Second question. I reconstructed the order lifecycle across four systems and measured each stage.

Median minutes, materially-late orders versus on-time:

- dispatch latency — 2.16 against 2.36. Late orders are dispatched *marginally faster*.
- **driver assigned to pickup — 37.5 against 20.5. Seventeen minutes.**
- transit — 50.3 against 46.4. About four minutes.

**Eighty-one percent of the excess delay sits between assigning a driver and collecting the food.**
Dispatch contributes negative. So the honest answer to *should we buy an AI delay-prediction
system* is: it would make the estimate of the delay more accurate and remove none of it. A better
ETA model does not shorten a seventeen-minute wait outside a restaurant.

> Dashboard section 3.

And the complaint data corroborates it independently — 26.9 complaints per 100 late orders against
7.2 on time, from a different source system than the timestamps."

---

## 2:30 — What I could not prove (45 s)

> `ASSUMPTIONS.md`, U-2.

"Now the part I think matters most. Inside that seventeen minutes, is the kitchen slow, or is the
driver arriving too early? Those need completely different fixes.

I can't tell you. The food-ready timestamp exists for **160 of 1,600 orders**, it's manually typed
by restaurant staff, and **60 of those are recorded after the pickup already happened** — which is
physically impossible.

> Dashboard, M4 row in the metrics table.

So I do publish the idle-wait figure, but the caveat is *in the metric row itself*, marked
LOW CONFIDENCE and explicitly not a basis for investment. It doesn't live in a footnote where it
can get dropped from a slide.

That's the recommendation: the next investment isn't an ETA model, it's a system-generated
food-ready event. Small engineering change, and it converts the largest known problem from
*located* to *actionable*."

---

## 3:15 — That it actually runs (45 s)

```bash
make run RUN_DATE=2026-08-29
```

"One command, ingest through publish. Four retrieval modes — SQL, flat files, nested JSON and a
paginated API.

> Point at the RETRY / RECOVERED lines.

The API injects an HTTP 500 and a 429; you can see them retried with backoff and recovered. Every
raw response body is preserved before parsing, including the failures.

```bash
make run RUN_DATE=2026-08-29    # again
```

Same run date, and the output is byte-identical — each partition is replaced in one transaction
rather than appended.

```bash
make run RUN_DATE=2026-08-29 --chaos stale_data
```

And when a required check fails, the run exits non-zero and **publishes nothing**. Every run,
every check and every source row count is recorded in the `meta` schema, so 'did last night's run
work' is a query, not an archaeology exercise."

---

## 4:00 — Close (20 s)

"To summarise the judgement call: the easy deliverable was one number. What the client actually
needed was to know that their number is a choice nobody has made, that the delay is in a stage an
ETA model can't touch, and that the question they'd most want answered next needs instrumentation
they don't have yet."

---

## Backup answers

**"Why not just use the 10-minute definition?"**
Because it's the Support Lead's position, not a ratified rule. Adopting it would repeat the exact
mistake — one function silently deciding a business threshold. The full curve is published so the
choice is visible.

**"Isn't 56% just wrong?"**
No, and that matters. It's arithmetically correct and reproduces the client's own
`order_outcomes.csv` exactly — checked every run by `cross.client_kpi_reconciliation`. Saying "your
number is wrong" would be false and would lose the room. It's correct and not decision-useful.

**"Why exclude the 37 delivered orders with no timestamp?"**
Three options: call them late (56.39 → 57.44%, which asserts a fact not in evidence), call them
on-time (understates), or exclude and report the exclusion. Only the third is defensible. It's A-2
in `ASSUMPTIONS.md` and the caveat ships attached to the metric.

**"Why Postgres instead of a notebook?"**
The class-8 question was whether it runs tomorrow without the person who wrote it. Layered schemas
give each stage a trust boundary, the `meta` schema makes runs auditable, and partition-scoped
replacement makes reruns safe.

**"What would you do with more time?"**
Chase U-2 first — the instrumentation gap. Then a run history, so these become trends rather than
one snapshot. Cost data would let the complaint rate become a money figure, which is what actually
moves an investment decision.
