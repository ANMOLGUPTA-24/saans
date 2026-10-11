# Submission form — answers to paste

Form: <https://www.wemakedevs.org/aws/env/submit>

---

## Part 2 · Project Details

### Project title
```
Saans — the bad air day protocol for Indian schools
```

### Track
**Air.** ☑

> Not Waste and Energy. Saans is about PM2.5, CPCB bands and children's respiratory
> exposure. Each track is judged on its own, so the track you tick decides who you are
> compared against.

### GitHub link to project
```
https://github.com/ANMOLGUPTA-24/saans
```

### Deployed link to project
```
https://anmolgupta-24.github.io/saans/
```

### YouTube video demo link
*(paste after upload — `build/saans-demo-narrated.mp4`, 2:43)*

---

### What does your project do?

```
Every morning a school in Delhi has to answer four questions before the gates open:
does assembly happen outside, does the games period happen, do the windows stay open,
who gets a mask. In practice it is answered by glancing at a colour in a phone app.

That colour cannot answer it. An AQI reading is an index for a city for a day. What a
child actually absorbs is a dose — concentration, times how long they are outside,
times how hard they are breathing. A child at vigorous play moves roughly three times
the air through their lungs as one standing in assembly, so the same reading delivers
three times the dose. Nobody computes that, so nobody sees it.

Saans does. At 05:45 it pulls the hourly forecast, prices every option for every
outdoor period, puts each one to a policy engine, and publishes a decision per class
with the clause that produced it — then writes it to a ledger, renders a bilingual
notice in Hindi and English, and emails it to the principal and the parents of
children on the school's respiratory register, before 07:00.

Three things make it more than a dashboard:

1. It budgets dose, not index. The unit throughout is µg·h/m³, exertion-weighted,
   measured against the WHO 2021 guideline week of 150 µg·h. On an ordinary October
   morning at 68 µg/m³ — which CPCB calls merely "Moderate" — one games period costs
   135% of a child's entire WHO week, and a full school day costs 208%.

2. Decisions are per class. A class carrying children on the respiratory register is
   protected at India's NAAQS standard of 60 µg/m³; a class with nobody on it is not.
   On a borderline day you can watch one class keep its recess outdoors while the
   others come in. That is a policy engine discriminating, not a blanket ban.

3. It tries not to take the period away. For each activity it tries, in order: hold it
   outdoors, move it into the cleanest hour of the day, and only then indoors — and the
   notice states plainly that a shut unfiltered classroom still admits about half the
   outdoor particulate. A protocol that only ever says no gets switched off in a
   fortnight.

Who it is for: the principal who has to make the call, and the parents of the children
on the register. Scale: the same protocol runs across all 772 schools inside the Delhi
NCT boundary that OpenStreetMap names and locates. Today, at every one of them, a
single games period costs more than a child's entire WHO weekly budget.

Measured, not claimed: replayed over real measured air, the protocol prevents 42% of a
child's inhaled dose over the last fortnight and 47% across the November 2025 smog
season. The figure I would defend hardest is a different one — on 28 September, with
PM2.5 at 29 µg/m³, it changed nothing at all.
```

---

### How did you use AWS in your project?

```
AWS OPEN SOURCE

• Cedar (via cedarpy) — the decision engine, not decoration. The school's bad-air
  circular is written as nine annotated Cedar policies in
  protocol/school_protocol.cedar. An activity stays outdoors only if Cedar returns
  ALLOW for that class, that period and that hour's evidence, and every denial cites
  its numbered clause in the principal's own words. The rule the whole project is
  built on is that no language model decides anything that affects a child's lungs —
  Cedar decides, the model writes one sentence of prose behind a guard. Evaluation
  errors fail closed: a protocol that cannot be evaluated is not permission.

• Strands Agents SDK — the agent, with four tools over the forecast, the protocol, the
  decision ledger and the clause text. It drafts the opening line of the notice a
  parent reads first, and answers questions about past decisions from the ledger,
  citing the clause. It runs against a local Ollama model, so there is no API key and
  no inference spend.

• LocalStack — stands in for the four managed services below, which is what makes the
  whole project runnable on the Build It path with no AWS account and no card.

AWS SERVICES (exercised through LocalStack; the same boto3 calls run unchanged against
real AWS with one environment variable)

• Amazon DynamoDB — the decision ledger. Every morning's call, its evidence hash, its
  protocol hash and the clauses that fired, keyed by school and date, so a parent
  asking in a month's time gets the same answer the principal got that morning.

• Amazon S3 — the bilingual notice, stored exactly as it went home.

• Amazon EventBridge — the 05:45 IST rule, cron(15 0 * * ? *). The decision has to
  exist before the principal needs it, not when someone remembers to click.

• Amazon SES — delivery to the principal and to the register's parents.

DEPLOYMENT TO REAL AWS

deploy/aws_deploy.py puts the whole thing on a real account in one command: a Lambda
behind a public Function URL (1M requests a month, always free — deliberately no API
Gateway, which is the part that would bill), the real DynamoDB table, the notices
bucket, a least-privilege IAM role scoped to just those, and the EventBridge rule.
deploy/aws_destroy.py removes all of it, because a deploy script without a teardown
script is how a student ends up with a bill.

The package is 10.6 MB zipped and ships cedarpy's manylinux wheel, which is the only
reason a Rust policy engine runs in a Python Lambda with no container build. I verified
it without an account by invoking the built artifact through Mangum with real Function
URL events: all eight routes return 200 and Cedar evaluates inside the zip. I could not
run the live deploy — my AWS account is on the new Free Plan and its restrictions
blocked IAM access-key creation (see the feedback section).
```

---

### Blog links
*(optional — leave blank, or publish the "what fought back" material from
`docs/writeup.md` on AWS Builder Center; top 5 blogs win AirPods and it is a separate
prize pool with far fewer entrants)*

---

### Team leader's contributions

```
Solo project — I built all of it.

• Evidence layer: live PM2.5 and mixing-layer height from Open-Meteo CAMS and ERA5
  (free, no key), plus 772 Delhi school locations and the NCT boundary from
  OpenStreetMap, clipped point-in-polygon to the city border.
• The dose model: exertion-weighted inhaled dose in µg·h/m³ against the WHO guideline
  week, including the indoor-infiltration and breathing-rate factors.
• The protocol: nine annotated Cedar policies, and the engine that puts every decision
  through them and maps denials back to the clause text.
• The decision engine: prices hold / relocate / indoors for every period, decides
  chronologically so the daily stop-loss works, and per class.
• The agent: Strands with four tools on a local model, plus the guard that validates
  its draft against the decision record.
• AWS: DynamoDB ledger, S3 notice store, EventBridge schedule, SES delivery via
  LocalStack, and the one-command Lambda deploy and teardown scripts.
• Impact measurement: replay over real measured days, and a decision-stability analysis
  across ±40% forecast error.
• The dashboard, the bilingual parent notice, the published static site, and the
  3-minute demo video.
• 67 tests covering the clause index, integer-only Cedar context, every clause firing
  on its own case and not one step below its threshold, failing closed, the dose
  arithmetic, the per-child weighted mean, and every guard rejection.

AI tools used: Claude Code (Claude Opus 5) as a pair-programming tool throughout. The
model shipped inside the product is llama3.1:8b via Ollama, used only to draft the
notice's opening sentence, behind the guard.
```

---

## Part 3 · Feedback

### Help us evaluate you: your feedback on the AWS services you used

```
Cedar — the error message when you pass a float is the single biggest trap. Cedar has
no floating-point type, which is reasonable, but the failure surfaces as
"failed to build request: data did not match any untagged enum RawCedarValueJson".
Nothing in that mentions numbers or floats. I lost real time before working out that
every µg/m³ reading had to be rounded to an integer on the way in. An error naming the
offending attribute and its type would have made it a thirty-second fix.

Cedar diagnostics — is_authorized returns determining policies as positional ids
(policy0, policy1, …) rather than the @id annotation I wrote on each clause. My whole
product depends on telling a parent which numbered clause kept their child inside, so I
had to parse the policy file myself and map file order to those indices. That mapping is
brittle enough that I wrote a test specifically to catch it drifting. Honouring @id in
the diagnostics would remove a sharp edge for anyone doing explainable authorization.

Strands Agents SDK — tool calling is unreliable with small local models. My agent
answered "I do not have it on record" while the record sat one tool call away. Strands
makes Bedrock the easy path, which is fair, but the Build It track pushes you to local
models, and the docs do not warn that a 7–8B model will often not chain tools. I had to
restructure so the agent is handed a pre-retrieved record and only writes prose. That
turned out to be a better design, but I found it by debugging, not from the docs.

LocalStack — the :stable image now refuses to start without LOCALSTACK_AUTH_TOKEN and
exits with a licence error. Nothing on the hackathon's own resources page signals that
the obvious tag is now gated; I had to find that the community image works by pinning
3.7.2. Worth flagging in the tour's Build It guidance, since LocalStack is listed there.

AWS Free Plan onboarding — this one actually stopped me shipping. I created an account
with $100 in credits and 184 days, then could not create an IAM user access key: the
console bounced me to /billing/signup/incomplete, which says the account is "on free
plan" with "limited access to certain services" and offers "Upgrade plan". It never says
*which* services are limited, so there is no way to tell whether you are blocked by the
plan tier or by a payment verification still clearing (the page mentions a $1 hold for
3–5 days). For a student on a deadline with working, tested deploy scripts, that is the
difference between deploying and not. Naming the restricted services explicitly, and
separating "your plan does not allow this" from "your payment is still verifying", would
have saved the submission.

SES — sandbox-only is the right default, but needing to verify each recipient makes a
parent-notification flow awkward to demo honestly. I ended up showing it against
LocalStack instead.
```

### What did you like about the AWS services you used?

```
Cedar is the reason this project has a spine. Being able to write the school's actual
circular as policy — thresholds, exceptions and all — and then have the application be
physically unable to hold a period outdoors without an ALLOW, changed what the project
is. The annotations are the quiet brilliance: I put the principal's own wording in an
@clause annotation next to each rule, so the notice that goes home can quote the exact
clause that kept a child inside. Forbid-overrides-permit meant the "normal school day"
default and the exceptions compose correctly without me sequencing anything. And
cedarpy shipping a manylinux wheel is why a Rust policy engine runs inside a Python
Lambda with no container build — a 10.6 MB zip, which I did not expect.

Strands Agents SDK — the @tool decorator is about as low-ceremony as this gets: a typed
Python function with a docstring becomes a tool, no schema written by hand. Being able
to point it at a local Ollama model with one line meant the whole agent cost nothing to
run, which mattered on a student budget.

DynamoDB — on-demand billing plus a composite key was exactly right for a decision
ledger. School as partition, date as sort, query descending for history: no capacity
planning, no decisions to make, and 25 GB always free means a ledger like this is
genuinely free forever.

EventBridge — a cron rule is one API call and costs nothing, and "the decision must
exist before 07:00" is a scheduling problem, not an application problem. Good fit.

Lambda Function URLs — the detail I appreciated most on the cost side. Getting a public
HTTPS endpoint without API Gateway keeps a hobby deployment inside the always-free tier
instead of accruing per-request charges. More student projects should know this exists.

LocalStack (once pinned) — exercising real DynamoDB, S3, EventBridge and SES API calls
with no account meant I could build and test the entire AWS path before I had
credentials, and the same boto3 calls deploy to real AWS with one environment variable.
That is exactly what the Build It path should feel like.
```
