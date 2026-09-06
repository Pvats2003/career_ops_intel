# Cost audit (FINAL GOD MODE Part 17)

What this system spends real money on, where that spend is controlled, and
what changed as a result of this audit. Every number below is either read
from the code paths that actually run, or — where a dollar figure would
require guessing at Anthropic's current per-model pricing — deliberately
left as a token count instead of a fabricated price.

## The only metered cost: Anthropic API calls

Every LLM call in this system funnels through one method:
`AnthropicLLMProvider.complete_json()` (`src/job_agent/llm/provider.py`).
There are five call sites, all optional and all degrading to a
deterministic fallback rather than blocking on cost or availability:

| Call site | Triggered by | Fallback when unavailable/unconfigured |
|---|---|---|
| `matching/semantic.py` | Every `jobs match` run, once per job (before caching) | Deterministic-only scoring; `JobMatch.concerns` notes it |
| `resume/tailor.py` | User clicks "Tailor resume" on a job | Deterministic resume assembly, `generated_by="deterministic"` |
| `applications/cover_letter.py` | User clicks "Generate cover letter" | Deterministic template, `generated_by="deterministic"` |
| `applications/answer_engine.py` | User asks the application assistant a question | `requires_human=True`, never a guessed answer |
| `candidate/career_chat.py` | User asks Career Chat a question | `_deterministic_fallback()` — real data, no LLM prose |

None of the five ever runs unprompted in a way that isn't already
throttled: the highest-volume one (semantic matching) is the one this
audit checked first.

### Existing cost control: match caching (Phase 16 / task #113)

`matching/service.py`'s `run_matches()` computes a cache key from the job's
content, the candidate's profile, and the scoring config
(`matching/cache.py:compute_match_cache_key`) before doing any work. If the
latest `JobMatch` row for that (job, candidate) pair was computed under an
identical key, it's reused as-is — **no LLM call, no new row.** Re-running
`jobs match` against an unchanged job/profile is free. This was verified
still in place and unmodified by this audit; no regression found here.

### Existing cost control: query-gated adapters (task #113)

Job-source adapters (Adzuna, in particular) are not themselves LLM-metered
— Adzuna's Jobs API is free within its documented rate limits — but request
*volume* is still bounded: `job_agent/jobs/sources/adzuna.py` caps request
count at `len(countries) * max_queries` per scan, both knobs read from
`config/sources.yaml` and the candidate's generated search-query portfolio,
never unbounded pagination. Greenhouse/Lever/Remotive/Arbeitnow adapters are
similarly one-request-per-configured-board, not open-ended crawls.

### Existing cost control: bounded retries

Every LLM call site retries **at most once** on `LLMOutputValidationError`
(malformed output) before falling back — so a single API call never becomes
an unbounded retry loop. Worst case per user action is 2x the base cost,
never more.

### Existing cost control: bounded output

`AnthropicLLMProvider` defaults to `max_tokens=1024` per call, and every
call forces structured tool-use output (`tool_choice`) rather than
open-ended free text — the model can't run long trying to produce prose
around the answer.

## The gap this audit found and fixed

`AnthropicLLMProvider.complete_json()` already computed real, exact
per-call usage from the API's own response (`response.usage.input_tokens` /
`.output_tokens`, plus measured latency) into an `LLMCallMetadata` object —
but every one of the five call sites discarded it (`_meta`, `meta`
unused past the return). The system was computing its own real cost data
and then throwing it away; there was no way to see how many tokens had
actually been spent, or on what, without instrumenting the code by hand.

**Fix:** `complete_json()` now logs one structured event
(`component="llm.cost"`) per successful call, via the existing
`log_event()` / `redact_text()`-backed structured JSON logger
(`job_agent/logging/setup.py`) — the same logging path already used
throughout the codebase, so this required no new infrastructure. Each line
carries `provider`, `model`, `prompt_version`, `input_tokens`,
`output_tokens`, and `duration_ms`. A failed call (raises before usage
data exists) never logs — no fabricated/partial usage line.

Because this lives in the one shared `complete_json()` implementation, it
covers all five call sites — and any future one — without touching any of
them individually.

**What this enables today:** grep the running server's JSON logs for
`"component": "llm.cost"` to see exactly what was spent, filterable by
`prompt_version` to see which feature (semantic matching vs. cover letters
vs. career chat, etc.) is the heaviest. Summing `input_tokens` /
`output_tokens` over a period gives an exact token count for that period —
converting that to a dollar figure requires the model's current published
per-token price, which this system deliberately does not hardcode (pricing
changes over time and a stale constant would silently misreport spend).

**What this does not do:** persist usage to the database or add a
dashboard. `SystemEvent` (`db/models.py`) already exists as a DB-backed
mirror of structured events but nothing in the codebase currently writes
to it (a pre-existing gap, out of scope for this audit) — logging is real,
observable today, and adding a persisted store/dashboard on top of it later
is a natural next step, not one this "final polish" pass should absorb
given the size and risk of touching every call site's return-value plumbing
to thread a DB session through.

## Verification

- `tests/unit/test_llm_provider.py` — two new tests: a successful call logs
  the real token counts from the fake API response; a failed call logs
  nothing.
- Full backend suite: 1267 passed (1265 baseline + 2 new), zero
  regressions.
