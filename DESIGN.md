# Design discussion 

## 1. Production rollout

Most of the pieces are here; production is mostly hardening and splitting them.

- **Separate extraction and bank reconciliation into distinct stages.** Today one process
  does both. Splitting them means matching can be re-run and iterated without re-running
  (and re-paying for) extraction, and the reconciliation logic — which could use more
  nuance — can evolve on its own.
- **Run behind an async worker / workflow engine** rather than a single script. Human
  review is the natural interrupt point: the `review` bucket is where a person steps in.
- **Resilience against provider failures.** We'd likely want a retry mechanism (with
  backoff) on transient model/API errors, and possibly a circuit-breaker pattern so that if
  a model provider goes offline the pipeline degrades gracefully rather than hammering a
  dead endpoint.
- **Improve observability.** We already emit per-call traces; the gap is turning those
  into something you'd actually operate on.
- **Versioning.** Version the model, the prompt, the schema, and the golden set so results
  are reproducible and a regression is attributable to a specific change.
- **Grow the golden set.** Six invoices is enough to sanity-check, not to eval properly.
- **Per-attribute prompt tuning.** Field-specific examples of good and bad extractions —
  which help with both hallucinations and misses. I played with this for `po_reference`
  with good results (a label-specific variant made every model pass the invoice_08 trap);
  I kept the generic rule live instead, since that particular example overfits the golden
  set — but it shows the technique works.
- **Add a judge / guardrail step** that verifies the quoted span really is the right source
  for that field, and that the returned value actually matches the quote.

## 2. Catching regressions

- **Weight fields by importance (a future improvement — not done yet).** Today every field
  counts equally; it shouldn't. `po_reference` is the most error-prone field but isn't used
  in bank reconciliation (it isn't in the bank data), so it could be heavily down-weighted
  or even skipped — a regression there is nearly harmless, unlike one on amount or
  invoice_id. Adding per-field weights would give a clearer overall score and make a
  regression on what matters visible instead of averaged away.
- **CI/CD around the eval.** Any change that can move the numbers (prompt, model, schema)
  should run the golden set in CI and flag regressions automatically, so a regression is
  caught at change time rather than after it ships.
- A regression is read through the harness's existing lens: a new **hallucination**
  (confident wrong value) is worse than a new **miss** (honest abstention), which just
  routes to review.
- Versioning (§1) is what lets a moved number be attributed to a specific model/prompt
  change.
- **Track metrics and alert on them.** Beyond CI, monitor the live system: track metrics
  the pipeline already produces — e.g. the triage mix (auto/review/reject ratio) and
  per-field abstention / consensus-disagreement rates — and alert when a tenant drifts from
  its baseline, so a regression is caught before a customer complains.

## 3. Cost and latency

Latency isn't the main lever here: it's heavily influenced by the current state of each
provider and is a bit random, and cheaper models tend to be *faster* anyway, so cost and
latency mostly move together. So this is mostly about cost — where the key finding is that
**cheaper models performed really well** on this task, so the budget is better spent on a
second read or a judge than on a bigger model.

- **Model choice — cheaper by default.** Cheap models did well and are usually faster;
  there's no reason to reach for an expensive one on this task.
- **Consensus (a second read)** filters hallucinations without needing a bigger model.
- **A future judge** targets the actual failure mode (wrong values) in a way raw model size
  does not.

Consensus and a judge do add their own cost and latency (each is an extra call), but in my
opinion that still seems more worth it than reaching for a more expensive model — because
they attack precision directly. And the extra call is cheap next to a bigger model: on the
golden set a two-read haiku consensus runs **~$0.009 per invoice**, less than a **single**
opus pass (**~$0.03**, or ~$0.05 with vision) — so the whole second-opinion mechanism costs
less than one call to the expensive model.

## 4. Drawing the line

- **Deterministic code is better for the obvious reasons** — reproducible, auditable,
  testable — so everything downstream of the value read stays deterministic.
- **Use the LLM only to extract the value.** And prefer PDF-text or OCR input over vision:
  it's deterministic and easier to eval and to check grounding for. For image-only PDFs,
  use **OCR + vision** for consensus.
- **An LLM must never execute a bank transfer on its own — that's a hard no.** Moving money
  is a human decision. I see the LLM's role here as double-checking human work, at least in
  earlier versions: it can verify transfers and point a human at what looks wrong, but the
  transfer itself is always initiated and approved by a person.
- **Where I'd resist an LLM even though it would work:** deciding the match itself. You
  could hand an LLM the transactions CSV plus our extractions and ask it to mark them by
  some criteria, but we can build a deterministic system for detecting how close the data
  is — so there's no match benefit to putting a model on that decision.

> **Candid note on the matcher.** The matcher / triage stage was a bit rushed. The core
> idea — two independent scores, identity (match) and reconciliation (approval) — is in my
> opinion good and the right structure to build on, but with more time I'd put more work
> into the matching logic itself.

## 5. Extra work / stretch challenges

Beyond the four core tasks, a few extras are already in the codebase:

- **Evidence spans + grounding (stretch C).** Every field carries a verbatim `source_quote`,
  and a grounding check verifies that quote actually appears in the source text
  (`quote_found`). Together with consensus this is what catches the invoice_08 trap — a
  model can quote something, but if the quote isn't really in the source (or the partner
  view disagrees) the value is dropped. It's currently a quote-in-source check rather than a
  page/char span; the judge step in §1 would extend it to "does the value match the quote."
- **Consensus as derived confidence.** Rather than trust a model's self-reported confidence,
  we run three independent reads (OCR / PDF-text / vision) and keep a value only when two
  agree — agreement-across-views is the confidence signal, and it doubles as a hallucination
  filter.
- **Cost / usage tracking (toward stretch B, observability).** Every call records tokens and
  real USD cost, and the eval attributes consensus cost back to its underlying reads. This
  is what backs the numbers in §3. Full structured tracing shipped to a store is still a gap.
- **Multi-model eval sweep.** `make eval-all` runs the golden set across several models and
  reports accuracy, grounding, and cost side by side — the basis for the "cheaper models are
  good enough" finding.

Not done: the **self-correction loop (stretch A)** — re-prompting a low-confidence field
with a narrower strategy. The judge / guardrail step proposed in §1 is the natural place to
grow into it.
