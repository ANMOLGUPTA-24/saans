# Saans — 3-minute demo video script

**Hard limit: 2:55.** The rules say judges score what the video shows; a feature that
exists only in the writeup does not count. So every claim below is shown on screen.

Record at 1280×800 or larger. Browser zoom ~110% so numbers are legible after YouTube
compression. Close other tabs. Have the server and LocalStack already running — do not
film a boot sequence.

**Before recording:** restart the server so caches are warm, and press *Run the morning
job* once so the ledger has a row (then reload to a clean page for the take).

---

## 0:00–0:22 · The problem, with a number

> **On screen:** the top of the page — the 68 µg/m³ band, the school, the date.

"It's a Sunday morning in Delhi. PM2.5 is 68 micrograms. CPCB calls that *Moderate* —
an unremarkable day, a month before the smog season even starts.

At a school four kilometres from here, someone has to decide before seven o'clock
whether the games period happens."

---

## 0:22–0:52 · Why AQI can't answer that

> **On screen:** scroll to §03 *Dose, not index*. Let the five stat tiles land.
> Then scroll back up to the decision table and point at the Games period row.

"An index can't answer it, because an index is a colour for a city for a day. What a
child takes in is a *dose* — concentration, times time outdoors, times how hard they're
breathing. A child at games moves about three times the air through their lungs.

So: that one games period, on this unremarkable day, costs a child **a hundred and
thirty-six percent of their entire WHO weekly budget**. One period. One week's budget.
A full school day here spends two of them.

That's the number nobody sees, because nobody is computing it."

---

## 0:52–1:35 · The decision, and the thing that makes it trustworthy

> **On screen:** the decision table. Hover a `P3` chip so the clause tooltip shows.
> Then scroll to §05 and show the Cedar clauses. Scroll back.

"Saans decides it. Per class — because Class 6-B has three children on the respiratory
register and Class 11-C has none, and they are not in the same position.

Every row cites the clause that produced it. And here's the clause — *this* is the
school's circular, written in **Cedar**, AWS's open-source policy language.

This is not a prompt. The rule the whole project is built on is: **no language model
decides anything that affects a child's lungs.** An activity stays outdoors only if
Cedar returns ALLOW. The model's job is one sentence of prose, and I'll show you what
happens when it gets that wrong.

And look at Class 11-C — recess, *held outdoors*. The protocol isn't a blanket ban.
It's a policy engine, and you can watch it discriminate."

---

## 1:35–2:05 · It tries not to take the period away

> **On screen:** §02 chart — point at the "cleanest" marker. Then a `moved to a cleaner
> hour` row if one is present; otherwise say the line over the chart.

"Before it takes anything away, Saans tries to keep it. It prices every option, finds
the cleanest hour in the school day, and asks whether moving the period there is enough.
Same activity, same exertion, different air — the recommendation a dashboard never
makes.

Only if that fails does the class go inside. And the notice says plainly that indoors
is a *reduction*, not an escape: a shut unfiltered classroom still lets in about half."

---

## 2:05–2:35 · AWS, and the receipts

> **On screen:** press **Run the morning job**. Let the receipts block render. Then
> scroll to §07 and show the four green service pills and the ledger table.

"One button runs the whole morning. Decide, draft, write, store, send.

**Strands Agents SDK** — AWS's open-source agent framework — runs the agent against a
local model, so there's no API key and no spend. **DynamoDB** holds the decision ledger.
**S3** stores the notice exactly as it went home. **EventBridge** carries the 05:45
rule. **SES** delivers it.

All of it on the Build It path — LocalStack, no AWS account, no card. The same boto3
calls run against real AWS with one environment variable.

And there's the guard: it checks the model's sentence against the record, and rejects
it if it states a figure that isn't there, or claims indoors is safe. During the build
it caught the model twice, for real errors."

---

## 2:35–2:55 · What it's worth, and the quiet day

> **On screen:** §04 — the impact tiles. Click **Nov 2025 smog**. Then scroll the
> replay table to the 2026-09-28 row with "nothing to do".

"Replayed over real measured air: **forty-two percent** of a child's inhaled dose
prevented over the last fortnight. Forty-seven percent across last November's smog
season.

But this is the row I'd point at. September the twenty-eighth. Twenty-nine micrograms.
Clean air. The protocol did **nothing at all**.

Because a protocol that fires on a good day gets switched off in a fortnight — and then
it isn't there on the day it matters."

---

## Shot list / checklist

- [ ] Page loaded, no console errors, ledger has at least one row
- [ ] Hover a clause chip so the tooltip is visibly captured
- [ ] Press *Run the morning job* **live** on camera — the receipts are the proof
- [ ] Show all four AWS service pills green
- [ ] Click the *Nov 2025 smog* toggle live
- [ ] End on the 2026-09-28 "nothing to do" row
- [ ] Under 3:00. Check before uploading.
- [ ] Upload to YouTube, set **Public or Unlisted**
- [ ] **Open the link in a signed-out browser window and confirm it plays**

## Things not to do

- Don't open an IDE or show code files. The page carries the story; code reading eats
  the clock.
- Don't apologise for the synthetic roster on camera — the README states it, and the
  air data is real, which is the part that matters.
- Don't read the clause text aloud word for word. Point at it and move.
