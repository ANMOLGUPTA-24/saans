# Saans — 3-minute demo video script

**Hard limit: 2:55.** The rules say judges score what the video shows, and there is no
live demo — the video *is* the submission. Every claim below is visible on screen.

Record at 1280×800+, browser zoom ~110%. Two tabs, both already loaded:

- **Tab A** — the live site: <https://saans-air-protocol.lovable.app>
- **Tab B** — the working app: `http://localhost:8000` (server + LocalStack already up,
  and press *Run the morning job* once beforehand so the ledger has a row, then reload)

Do not film a boot sequence. Do not open an IDE.

---

## 0:00–0:25 · The finding, stated cold

> **Tab A**, hero. Let the headline sit on screen.

"Nine hundred and twenty-two schools in Delhi. Real schools — every one OpenStreetMap
has a name and a location for.

At **all** of them, today, a single games period costs a child more than their entire
WHO weekly limit for air pollution. Not the smog season. An ordinary Sunday in October.

Four hundred and seven of them are in air CPCB calls *Poor*. And no school in that city
is currently computing this, because the number nobody computes is the one that
matters."

---

## 0:25–0:55 · Why the AQI can't tell them

> **Tab A**, scroll to *Dose, not index*. Pause on the three exertion cards, then on
> the 136% bar.

"An AQI reading is a colour, for a city, for a day. What a child absorbs is a **dose** —
concentration, times time outdoors, times how hard they are breathing.

And that last term is the one everybody drops. A child at games moves about three times
the air through their lungs as a child in assembly. Same air, triple the dose.

Run it: assembly twenty-one percent of a child's weekly budget. Recess forty-five. The
games period — **a hundred and thirty-six percent**. One period. One week's limit.
That's why 'Moderate' air is not moderate for a child at play."

---

## 0:55–1:35 · The decision, and why you can trust it

> **Tab A**, *Today's decision* table. Hover a `P3` chip so the clause tooltip shows.
> Scroll to *The protocol, as code* and rest on the pull-quote. Scroll back to the
> Class 11-C row.

"Saans decides it — per class, before seven in the morning. Every row cites the clause
that produced it.

And here is that clause. This is the school's circular written in **Cedar**, AWS's
open-source policy language. It is not a prompt.

That's the rule the whole project is built on: **no language model decides anything
that affects a child's lungs.** Cedar decides. The model writes one sentence of prose,
and I'll show you what happens when it gets that wrong.

Now look at Class 11-C — recess, *held outdoors*. It's the one class with nobody on the
respiratory register. Same evidence, different needs, different answer. That's a policy
engine discriminating, not a blanket ban."

---

## 1:35–1:55 · The map, and not taking the period away

> **Tab A**, the Delhi map. Hover one or two points.

"Every school, coloured by what a child takes in there today. You can see the gradient
across the city — this is not one number copied nine hundred times.

And before Saans takes a period away, it tries to keep it: it prices every option and
looks for the cleanest hour in the school day to move it into. Same activity, same
exertion, cleaner air. Indoors is the last resort — and the notice says plainly that a
shut unfiltered classroom still lets in about half."

---

## 1:55–2:20 · The question a judge is about to ask

> **Tab A**, *How wrong can the forecast be?*

"You should be asking: this is a forecast, so how do you know it's right?

There's no free ground-sensor feed for Delhi to check against, and quoting an accuracy
figure I can't back would be dishonest. So Saans answers the question that actually
matters for a safety tool — does the *decision* survive the forecast being wrong?

Every call is re-decided across plus or minus forty percent forecast error. **Every
games-period call holds across the whole band** — the decision carrying triple the dose
is the most robust one. The borderline calls are labelled *marginal*, because a tool
like this should not project confidence it hasn't earned."

---

## 2:20–2:45 · AWS, with receipts

> **Switch to Tab B.** Press **Run the morning job** live. Let the receipts render.
> Scroll to the four green service pills.

"One button runs the whole morning: decide, draft, write, store, send.

**Cedar** is the policy engine. **Strands Agents SDK** runs the agent on a local model —
no API key, no spend. **DynamoDB** holds the decision ledger, **S3** the notice exactly
as it went home, **EventBridge** the 05:45 rule, **SES** the delivery.

All on the Build It path — LocalStack, no AWS account, no card. Same boto3 calls run
against real AWS with one environment variable.

And there — the guard rejected the model's sentence, because it stated a number the
record doesn't support. It fell back to the deterministic summary and **said so.**
During the build it caught the model three times."

---

## 2:45–2:55 · The row I'd stake it on

> **Tab A**, *What it's worth*. Point at the highlighted 28 September row.

"Forty-two percent of a child's inhaled dose prevented over the last fortnight.

But this is the row. September the twenty-eighth. Twenty-nine micrograms. Clean air.
Saans did **nothing at all** — because a protocol that fires on a good day gets switched
off in a fortnight, and then it isn't there on the day it matters."

---

## Checklist

- [ ] Both tabs pre-loaded; ledger has a row; LocalStack up
- [ ] Clause tooltip visibly captured on hover
- [ ] *Run the morning job* pressed **live** — the receipts are the proof
- [ ] Four AWS pills green on screen
- [ ] End on the 28 September "nothing to do" row
- [ ] **Under 3:00** — check before uploading
- [ ] YouTube, Public or Unlisted
- [ ] **Open the link in a signed-out window and confirm it plays**

## Don't

- Don't show code files. The pages carry it; reading code eats the clock.
- Don't apologise on camera for the synthetic roster — the air, the 922 school
  locations and the standards are all real, and the site says which is which.
- Don't read clause text aloud word for word. Point and move.
