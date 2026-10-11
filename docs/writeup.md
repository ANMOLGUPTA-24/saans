# Saans — submission writeup

**Track:** Air · **Event:** Environmental Hacks, Bharat Builds Tour (WeMakeDevs × AWS)
**Live site:** <https://saans-air-protocol.lovable.app>
**Repository:** <https://github.com/ANMOLGUPTA-24/saans> · **Demo video:** *(YouTube, under 3:00)*

---

## The problem

Every morning a Delhi school has to answer four questions before the gates open: does
assembly happen outside, does the games period happen, do the windows stay open, who
gets a mask. In practice it's answered by glancing at a colour in a phone app.

That colour can't answer it. An AQI reading is an index for a city for a day. What a
child actually absorbs is a **dose** — concentration × time outdoors × how hard they're
breathing — and a child at vigorous play moves roughly three times the air through
their lungs as one sitting in assembly.

Price a single ordinary October morning at a real school in Shalimar Bagh, North West
Delhi, with PM2.5 at 68 µg/m³ — which CPCB calls merely *Moderate*, months before the
smog season:

| Period | Exertion | Dose | Share of a child's **weekly** WHO budget |
|---|---|---:|---:|
| Morning assembly | ×1 | 32 µg·h | 21% |
| Recess | ×2 | 67 µg·h | 45% |
| Games period | ×3 | 204 µg·h | **136%** |
| **One school day** | | **303 µg·h** | **202%** |

One games period spends more than a child's entire WHO guideline week. None of that is
visible in the words "AQI: Moderate", and no app in use at an Indian school computes it.

## What I built

Saans runs at 05:45, pulls the hourly forecast, prices every option for every outdoor
period, puts each one to a policy engine, and publishes a decision **per class** with
the clause that produced it — then writes it to a ledger, renders a bilingual notice,
and emails it to the principal and the register's parents before 07:00.

Three things distinguish it from a dashboard:

**1. It budgets dose, not index.** The unit throughout is µg·h/m³, exertion-weighted,
measured against the WHO 2021 guideline week of 150 µg·h. That is the only quantity a
school can actually spend or save.

**2. The protocol is Cedar, not a prompt.** The school's circular is written as nine
annotated Cedar policies. An activity stays outdoors only if Cedar returns `ALLOW` for
that class, that period, and that hour's evidence. Every denial cites a numbered clause
in the principal's own words. A principal can argue with a threshold and change it
without touching application code.

> **The rule the project is built on: no language model decides anything that affects a
> child's lungs.** The model writes one sentence of prose, behind a guard.

**3. It tries not to take the period away.** For each activity, in order: hold it
outdoors → move it into the cleanest hour of the day (same activity, same exertion,
different air) → only then indoors, and the notice states plainly that a shut
unfiltered classroom still admits about half the outdoor particulate. A protocol that
only ever says no gets switched off in a fortnight.

## Delhi, school by school

One school proves the protocol works; it does not show the size of the thing. Saans
runs the same protocol across **every school in Delhi that OpenStreetMap has a name and
a location for — 922 real places** (ODbL).

The air genuinely varies: 26 µg/m³ between the cleanest and dirtiest mapped school this
morning, 55 µg/m³ between the corners of the city. So these are 922 different
decisions, not one decision printed 922 times.

> **At all 922, a single games period today costs more than a child's entire WHO weekly
> budget.** 407 sit in CPCB *Poor*.

Dose is per child by construction, so this needs no enrolment figure and none is
invented. Values are interpolated from a ~40 km model grid, which the site states
plainly — nearby schools can share a reading.

## How wrong can the forecast be?

The obvious challenge: this acts on a global model's forecast. There is no keyless
ground-truth sensor feed for Delhi, and quoting a skill score without one would be
dishonest. So Saans answers the question that actually matters for a safety tool —
**does the decision survive the forecast being wrong?**

Every call is re-decided across **±40% forecast error**, wider than anyone claims for
CAMS:

- **All four games-period calls hold across the entire band.** The decision carrying
  triple the dose is the most robust one, which is the right way round.
- Seven borderline calls flip between −10% and −20%, and are labelled **marginal**.

A call flagged marginal is one Saans refuses to present with confidence it hasn't
earned. That is an honesty feature, not a weakness.

## Where AWS fits

The **Build It** path — AWS open-source tooling on a laptop, no AWS account, no card,
no inference bill.

| | |
|---|---|
| **Cedar** (`cedarpy`) | The protocol engine. Every decision is an authorization request; every denial cites its clause. Cedar has no float type, so evidence is rounded to whole µg/m³, metres and percent on the way in, and thresholds are written in the same units. Evaluation errors fail closed. |
| **Strands Agents SDK** | The agent — four tools over the forecast, the protocol, the ledger and the clause text — running against a local Ollama model, so no key and no spend. |
| **LocalStack** | Stands in for the four managed services below. The same boto3 calls run unchanged against real AWS; `SAANS_AWS=real` drops the endpoint override. |
| Amazon **DynamoDB** | Decision ledger: every morning's call, its evidence hash and its clauses, keyed by school and date. |
| Amazon **S3** | The notice, stored exactly as it went home. |
| Amazon **EventBridge** | The 05:45 IST rule, `cron(15 0 * * ? *)`. The decision must exist before the principal needs it. |
| Amazon **SES** | Delivery to the principal and the register's parents. |

## The guard, and why it earns its place

The likeliest way a project like this hurts somebody is not a wrong threshold — it's a
small model writing a fluent sentence with a wrong number in it, which a parent then
believes. So the model's draft is validated against the decision record before use. It
is rejected if it states a figure the record doesn't support, claims indoors is safe,
says a period was "cancelled" when nothing was cancelled, or flattens a mixed decision
into "all classes". Rejected drafts fall back to a deterministic summary, and the page
says so.

This is not hypothetical. During the build, llama3.1:8b's drafts were rejected twice
for real errors: once for claiming periods were "cancelled" (Saans never cancels — it
moves), once for "all outdoor periods" when Class 11-C was still outside.

## What it's worth, measured

Replayed over real measured air — no modelling of my own:

| Window | School days | Unmitigated | Under protocol | Dose prevented |
|---|---:|---:|---:|---:|
| Last fortnight (Delhi, Oct 2026) | 11 | 19.6 WHO-weeks | 11.4 | **42%** |
| Smog season (Delhi, 3–14 Nov 2025) | 10 | 18.6 WHO-weeks | 9.8 | **47%** |

The figure I'd defend hardest is a different one: on 2026-09-28, with PM2.5 at 29
µg/m³, **the protocol changed nothing at all.** Staying out of the way on clean days is
what keeps it switched on for the day it matters.

## What fought back

**The budget clause was degenerate and I had to tear it out.** My first version gated
the protocol directly on WHO's weekly budget. It sounds more rigorous and it was
useless: Delhi spends that budget by Tuesday, so every clause fired for every class
every day, all four classes returned byte-identical decisions, and the protocol stopped
discriminating entirely. The fix was to separate the two jobs — keep WHO as the
**yardstick impact is reported against**, and enforce **avoidable dose** instead: the
part of today's exposure the school can still choose not to take. That is the
difference between a true statement and an operational tool.

**Cedar has no floating-point type.** Every request failed with
`data did not match any untagged enum` until the whole evidence context was converted
to integers. Thresholds are now written in whole µg/m³ and metres so nothing a
threshold could turn on is lost.

**An internal inconsistency a judge would have caught.** The indoor fallback claims a
50% dose reduction, which assumes the windows are shut — but my windows clause was set
at 90 µg/m³, so between 60 and 90 the model was claiming a reduction it hadn't earned.
Windows now shut at 60, the NAAQS standard, and the two decisions are coupled.

**Uppercasing µ turns it into a capital Mu**, which reads as "MG". The table headers
were silently displaying milligrams — a thousand-fold units error — in a health tool.
Units now opt out of `text-transform`.

**LocalStack's `:stable` tag now demands a paid auth token.** Pinned to the `3.7.2`
community image.

## Honest about what's real

- **Real:** all air and weather data, live and historical (Open-Meteo CAMS + ERA5, free,
  no key); the location; CPCB breakpoints; India's NAAQS 24-hour standard; the WHO 2021
  guideline; the Cedar evaluation; the AWS calls; the dose arithmetic.
- **Synthetic, and labelled as such in the UI and README:** the roster — four classes,
  183 children, six on the respiratory register. Inventing health records for a named
  real school would be dishonest, and no logic depends on the names being real.
- **Approximations, stated:** exertion multipliers are a standard minute-ventilation
  ratio, not per-child measurement; indoor infiltration is taken as 0.5 for a shut
  unfiltered room. Both are single constants in `saans/school.py`.

## Limitations

Forecast, not sensor — CAMS is coarse, and a school beside a construction site will be
worse than it says; a ₹3,000 rooftop PM sensor is the obvious next input and the dose
maths doesn't change. Saans has no view inside the classroom. Relocation assumes
periods can be rescheduled within the day. Nothing here is medical advice, which is why
the notice never claims indoors is safe.

## Testing

54 offline tests plus one live-data test, running in under a second. They cover the
things that would hurt somebody if they were wrong: Cedar clause indices matching file
order (if those drift, every citation on every notice silently points at the wrong
clause), integer-only context, every clause firing on its own case *and not one step
below its threshold*, failing closed on an unevaluable protocol, the exertion and
infiltration arithmetic, chronological decision order, the per-child weighted mean
(summing per-child savings across classes overstates it fourfold), and every guard
rejection.

## AI tools used

Per the tour rules: built with **Claude Code (Claude Opus 5)** as a pair-programming
tool across the hackathon window. The runtime model shipped in the product is
**llama3.1:8b via Ollama**, used only to draft the notice's opening sentence, behind
the guard described above.

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
docker run -d --name saans-localstack -p 4566:4566 \
  -e SERVICES=dynamodb,s3,events,ses,sts localstack/localstack:3.7.2
ollama pull llama3.1:8b   # optional
AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test \
  .venv/bin/uvicorn saans.api:app --port 8000
```

Open <http://localhost:8000>. Change `LATITUDE` / `LONGITUDE` in `saans/school.py` to
point it at any school in India.
