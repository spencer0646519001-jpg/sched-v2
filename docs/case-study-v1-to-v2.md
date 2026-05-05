# Case Study: sched-mvp v1 to sched-v2

## What v1 told me I had to fix

When I showed sched-mvp v1 to engineering friends, the first thing they pointed
at was the engine module. It imported Django models directly, called OpenAI
inside scheduling logic, and the only path to test whether the scheduling code
was correct was to spin up a full Django test client. They were polite about
it. The verdict was: "this works, but you can't review it."

That feedback was specific enough to act on. v1 had answered "can this
scheduling workflow be demonstrated?" What it had not answered, and what I
wanted v2 to answer, was "can the backend boundaries be trusted enough that
someone can read this code and form an opinion about it?" I started v2 — a
full rewrite — to answer that second question.

## The 80-point hypothesis

Before getting into v2's architecture, I want to be explicit about a product
judgment I made early, because it shapes everything else.

The conventional answer to staff scheduling is a fully-optimized 100-point
schedule: the cleanest possible roster given hard constraints (skills, leave,
station coverage) and a fairness objective (workload balance, weekend
rotation). I considered building toward that. After ten years of monthly
schedules in Michelin kitchens, I came to believe it's the wrong shape of
answer for restaurant scheduling.

Here is what I observed in those ten years. Once an optimizer-style schedule
lands on a manager's desk, the manager spends their time pulling it apart. A
senior chef de partie is leaving for a stage next week, so the rotation needs
to ramp her cover up gradually. The new junior is in week two of their
orientation; they shouldn't be paired with the slowest cook on the line just
because that pair balances on paper. Two specific cooks have a known pace
problem when they work the same station; another pair is unusually fast and is
worth using on the busy nights. The pastry team is testing a new menu next
Thursday, so their shifts need to be lighter that day. None of these are
visible to the optimizer. All of them matter.

The result is that a 100-point machine schedule takes a manager *longer* to
finalize than a strong starting point would. Pulling apart something that
locally optimizes a metric — and re-checking that the rest still satisfies the
hard constraints — is harder than building forward. The schedule becomes
adversarial: the manager fights the optimizer to put back the things only they
can see.

So sched-v2 deliberately solves the inverse problem. The engine produces an
explainable 80-percent draft and a complete set of warnings (under-staffed
days, missing skills, leave conflicts, skill coverage gaps). The manager makes
the last 20 percent of decisions through natural-language refines, with an
explanation tool to surface why the engine made any given assignment. The four
user-facing pieces of the system — draft + warnings, natural-language refine,
per-day explanation, and CSV export — are not four parallel features. They are
the four moments of the manager's monthly workflow, in order: read the draft,
fix the obvious things in plain language, dig into one assignment that looks
wrong, and hand the finished schedule to the floor.

I might be wrong about this for other domains, where pure optimizer output is
genuinely close to deployable. For restaurant scheduling, this is the shape of
the problem I keep seeing across two countries and two languages of kitchen
work.

## What I read before rewriting

Before starting v2, I gave myself a week of reading. The architecture pattern
that mapped most cleanly onto what I needed was hexagonal architecture —
sometimes called ports and adapters. The core idea — keep the domain logic
free of framework and infrastructure concerns; let the framework call into the
domain through narrow interfaces, not the other way around — was directly the
inverse of what v1 had become.

I also spent time on Django-specific material around app boundaries: where to
put business logic that's bigger than a model and smaller than a service
layer, how to keep views thin, why fat models become a maintenance trap. And I
looked at how mature codebases handle the candidate-preview-apply pattern that
scheduling, e-commerce checkout, and data-pipeline orchestration all share
variants of: server-side artifact, ID-referenced, freshness check on apply.

A week is not deep expertise. It was enough to know what I was reaching for
and to recognize when v2 was drifting back toward v1's mistakes.

## How v2 was built

Four architectural constraints were settled before I wrote a line of v2 code:

1. **The engine is pure.** No Django imports, no DB calls, no model calls.
   The engine takes a typed input and returns a typed output. This was a
   direct response to the v1 lesson that engine-and-web tangling makes
   scheduling logic untestable in isolation — debugging a scheduling problem
   in v1 meant debugging the HTTP layer at the same time.
2. **The API layer stays thin.** It parses requests, delegates to services,
   and renders responses. Business logic does not live in views. The API is
   the system's only externally-reachable trust surface; the thinner it is,
   the easier it is to audit.
3. **Tenant-aware everywhere.** Every persistent record carries a tenant.
   Repositories, admin, and seed scripts are tenant-scoped. Multi-tenant from
   day one, not retrofitted.
4. **Services own workflow orchestration.** Preview, apply, save, export,
   refine, and explain are services. The engine doesn't know about workflows;
   the API doesn't run workflows directly. Workflows stay reorderable and
   replaceable without touching engine or API code.

Inside those four boundaries, I paired with Codex 5.5 on the implementation.
Codex is fast at writing code that fits a clearly-stated constraint; the
constraints were mine to set and to enforce when the implementation drifted.
The decisions are mine; the implementation velocity is the AI's.

Concrete examples of where I redirected, narrowed, or rejected AI suggestions
during this build are in the next section.

## AI-assisted development: where I redirected, narrowed, or rejected suggestions

### Product and domain decisions

**Layout.** The first cut of the monthly workspace page led with the schedule
grid: a large calendar matrix at the top, with controls, evaluation, and
warnings tucked underneath. I changed the order. The grid is now below the
controls, evaluation summary, warnings, and refine panel. A manager opening
the page mid-month wants to know what's wrong with the current draft — the
under-staffed days, the missing skill coverage, what the model thinks about a
recent refine — before they look at the draft itself. The grid is the last
thing they need to see, not the first.

**Refine semantics.** The first version of the refine parser required four
fields on every request: date, worker, shift, and station. If any of them
were missing the request was rejected. From watching managers actually
correct schedules, I knew this would not match how a correction is phrased.
A real correction is partial — `Spencer, swap to C-shift on 5/2` leaves the
station alone because the station isn't what's changing. I rewrote the parser
to support partial edits and at the same time made it stricter about
ambiguity: when the request really is missing information the system can't
infer (which Spencer? which 5/2?), the parser refuses rather than guesses.
The trade-off was that the deterministic test corpus had to grow to cover the
new partial-edit shapes; the refine layer ended up matching how managers
actually talk.

**Refine capability boundary.** An early draft of the refine layer treated
every input as either parseable into a structured edit or rejected outright.
That's too narrow for a scheduling assistant. A manager will phrase requests
like "make this month fairer across staff" or "rebalance the pastry station
for next week." These are real scheduling intents; they're just not safely
executable as a single narrow assignment edit. I split refine into four
states: executable (a valid structured edit, candidate preview created),
understood-but-not-executable (recognized as scheduling intent the system
doesn't safely execute), ambiguous-or-missing (the parser can tell something
is missing but not what), and non-scheduling (rejected). The model can engage
with abstract scheduling intent inside the domain — it's allowed to recognize
what "fairer" means — without that engagement leaking into write access.

### Deployment and portfolio decisions

**Tenant-aware completeness audit.** The deployment plan suggested moving
forward without a full admin or onboarding surface — those weren't blocking
the demo. I pushed back on a different question: this project claims to be
tenant-aware from day one, but if a hypothetical new restaurant wanted to use
it, where would the workers, shifts, stations, and rules actually come from?
I had not opened an admin once. Before deploying, I worked through what a
tenant-aware claim actually needs to be true: the seed command
(`seed_monthly_workspace_demo`) is documented as the path that produces the
`demo_kitchen` tenant, the DB-backed data shapes are written down, Django
admin is mounted only via `admin_local_settings` so it stays internal and out
of deploy settings, and the local admin runs on a separate port for local
verification. This wasn't a scope expansion — it was a completeness audit on
a capability the project was already claiming.

**Admin-to-frontend smoke test.** Once the local admin was working, the
natural assumption was that data visible there was also the data the monthly
workspace would render. I didn't trust that assumption on documentation
alone. Before deploying, I ran a small smoke test: change a worker through
admin, reload the monthly workspace, confirm the change shows up. The point
wasn't to verify a feature; it was to verify that admin and the monthly
workspace are reading the same DB-backed source rather than two parallel
fixture stores. The test passed quickly and was almost boring. It was also
the cheapest way to catch a class of bug — split source-of-truth — that's
expensive to find later.

**Positioning of v1 vs v2 (in progress).** The deployment plan from an
engineering-safety angle was to leave both versions reachable side-by-side:
sched-mvp v1 on host port 8000, sched-v2 on host port 8001. Both stay up;
nothing breaks. From a portfolio angle, I asked a different question: does
keeping v1 publicly reachable help the story I'm telling reviewers, or does
it muddy the message about what the main demo is? At the time of writing,
sched-v2 has just been deployed to `sched.spencerailab.com` and is in a
side-by-side stabilization window with v1 still reachable on the legacy host
port. Once v2 clears that window, v1 will be retired from public access and
kept only as a GitHub reference. I'm framing the rollout this way
deliberately — staging a portfolio demo cutover the same way I'd stage any
production change.

**Domain and HTTPS before going public.** The straightforward deployment path
was IP-based: get the container running on the rented server, point at the
IP, done. Domain and HTTPS could come later. I held the public posting back.
If the plan was to share this on LinkedIn or X as a portfolio piece, the
demo URL is going to be one of the first signals a reviewer sees. A naked
IP with a self-signed certificate is a different signal from
`sched.spencerailab.com` with a valid Let's Encrypt cert. I bought the
domain, configured the subdomain, set up Caddy as the HTTPS reverse proxy,
and only then started linking to it externally. This is presentation
judgment rather than feature work, but it changes how the project reads to
someone who clicks a link from a recruiter message.

## Technical decisions, and why each one matters to me personally

### Backend boundaries

I separated the system into engine, infra, services, and API:

- `app.engine` is pure scheduling logic.
- `app.infra` owns Django models and repositories.
- `app.services` owns workflows: preview, apply, save, export, refine,
  explain, monthly context assembly.
- `app.api` parses HTTP, renders the workspace, maps JSON, and delegates.

The reason this matters to me personally is that v1's pain was specifically
the failure of this separation. In v1, debugging a scheduling correctness
problem meant debugging the HTTP layer at the same time, because the engine
was reaching into Django models. I had been doing the equivalent thing in
kitchens for years without recognizing it: when the line and the pass aren't
separated cleanly, every problem becomes two problems at once.

### Preview, apply, and save

The lifecycle is explicit:

- **Preview** generates a candidate schedule and persists it server-side as a
  `MonthlyCandidatePreview` with an input fingerprint.
- **Apply** promotes a candidate by ID into the current `MonthlyWorkspace`.
- **Save** snapshots the workspace into an immutable `MonthlyPlanVersion`.
- **Export** reads the workspace or a saved version and returns CSV.

I think of this as the kitchen workflow: prep, service, breakdown. Once a
station moves from prep into service, you don't reach back and re-edit the
prep tray; you make the changes forward. The data flow respects that
direction.

### Candidate trust

Apply does not trust the browser. It re-loads the candidate by `candidate_id`
from the server, checks that the candidate's tenant and month match the
request, and verifies via input fingerprint that no relevant persisted input
has changed since the candidate was generated. Off-month writes are rejected
before any DB mutation.

The kitchen analogy is the back-of-house's relationship to the front-of-house
ticket. A handwritten ticket comes back to the pass; the pass re-reads it,
confirms it's for the correct table, and verifies it against what was
actually called. The ticket is not the source of truth; it's a request that
has to be re-validated against the plan. v2's API treats browser-submitted
candidates the same way.

### Bounded AI

Refine produces a candidate preview only. It cannot apply, cannot save,
cannot mutate the workspace. Explain is read-only and bounded to one selected
day. Scheduling intent that the system understands but does not safely
execute returns an honest understood-but-not-executable classification rather
than a force-parsed assignment edit. The offline AI intent eval harness
checks refine intent behavior across a fixed zh/ja/en corpus without calling
the OpenAI API.

The kitchen analogy is that a junior cook on day three is allowed to
recommend, ask questions, and propose. They are not allowed to drop a plate
on a guest's table. The ability to recognize a good idea is independent from
the authority to act on it. v2 keeps those two separate for the model layer.

## Engineering quality

The rewrite carries reviewer-visible engineering structure. Two numbers I'd
point at:

- **228 tests** under `tests/`, covering monthly schedule integration,
  workspace UI, refine and explain workflows, candidate trust, and reviewer
  stories. Tests run with in-memory SQLite via `tests/conftest.py` and strip
  `OPENAI_API_KEY` to prevent live model calls.
- **2,684 lines across `app/engine/`, none of them import Django.** The
  engine is verifiably independent of the framework. A scheduling-logic bug
  in v2 is debugged with a unit test, not by spinning up an HTTP layer.

The rest of the engineering surface is conventional: Ruff for lint, pytest
for the suite, Docker Compose for the rented-server deployment with a
project-scoped SQLite volume so rebuilds don't reset demo data, and `.env`
plus Compose project name kept separate from sched-mvp v1 so the two
deployments don't collide. None of these are clever; they are the discipline
of treating a portfolio project the way I'd treat anything that has to keep
running.

## Honest limitations — and the next iteration

What v2 is not, in its current form:

- Demo/localdev oriented rather than production SaaS hardened.
- No production auth, RBAC, or tenant access-control story.
- No production self-serve restaurant onboarding UI.
- SQLite-backed demo deployment rather than production database architecture.
- Saved versions exist; there is no full restore/versioning UI yet.

The two specific things I want to add before pointing recruiters at this
demo:

- **Observability layer.** Right now, the system produces logs and that's
  all. I want at least basic structured logging plus a per-request trace
  surface so a reviewer can see what the refine layer actually did on a given
  request. That's the next iteration.
- **Real model evaluation.** The current eval harness runs the deterministic
  local refine parser against a fixed corpus with a noop model client. It is
  regression coverage, not a model benchmark. The next iteration is a small
  live-model eval set that exercises the actual OpenAI refine path on a
  held-out corpus, so I can speak honestly about model quality, not just
  parser stability.

## What I'd do differently if starting again

Two changes I would make on day one:

- **Observability from the start, not retrofitted.** I treated logging as
  something to add later. The result is that I'm now budgeting time to
  backfill it before going public. On the next project, structured logging
  and a per-request trace surface go in during the first week, the same way
  migrations and tests do.
- **Postgres with row-level security from day one.** sched-v2 is tenant-aware
  in code — every record has a tenant FK and repositories are tenant-scoped.
  But the database itself is SQLite, without database-level tenant
  isolation. Knowing the project would carry multi-tenant semantics, I'd
  build on Postgres with row-level security from the first migration.
  Defense in depth on tenant isolation should not be an application-only
  concern.

## Why the rewrite matters

v1 answered "can this scheduling workflow be demonstrated?" That was a useful
question. v2 answers a different one: "is the backend boundary credible
enough that an engineer can read the code and trust what it does?" The
persistence shapes, the candidate-trust pattern, the bounded AI surface, and
the deterministic engine are all in service of that.

But the rewrite isn't only a cleanup pass. It is also where the 80-point
hypothesis from the start of this case study became the actual shape of the
code. The engine produces 80 percent. The manager produces the last 20
through bounded refines. The system never lets the model claim authority it
doesn't have. The rewrite mattered because it made the product judgment
legible — to me, and to anyone reading the code.
