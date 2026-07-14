# Evaluation summary

**Date:** 2026-07-14 · **Golden set:** 6 hand-labeled invoices (incl. one image-only
scan) · **Real API spend:** $1.72 (`make eval-all`, 6 models)

This run uses the **generic** `po_reference` rule — *"the buyer's number, not the
supplier's,"* naming no specific label. The alternative (disabled) version names
invoice_08's own distractor labels; it scores better but overfits the golden set. Keeping
it generic is the honest test.

## Headline: detection is solved — the problem is abstention on one field

Across all 6 models × 3 views, **six of the seven fields are 100%** — invoice_id,
supplier_name, amount, currency, invoice_date, due_date. Every model reads every one
correctly from OCR text, PDF text, or the page image alike. **All 15 view-level failures
are `po_reference`; nothing else ever fails.**

So the view *type* (OCR / PDF-text / vision) barely matters for reading values — the views
are essentially interchangeable at detection. The only hard problem is **knowing when
`po_reference` is empty** and abstaining instead of inventing a value.

## Consensus results (the pipeline's output)

| Model | Accuracy | Hall | Miss | Grounding | Consensus cost | Total cost |
|---|---|---|---|---|---|---|
| `openai/gpt-5.6-luna` | **100%** | 0 | 0 | 100% | $0.028 | **$0.053** |
| `anthropic/claude-haiku-4.5` | **100%** | 0 | 0 | 95% | $0.054 | $0.082 |
| `anthropic/claude-sonnet-5` | 98% | 0 | 1 | 100% | $0.156 | $0.251 |
| `openai/gpt-5.6-terra` | 98% | 0 | 1 | 100% | $0.139 | $0.346 |
| `openai/gpt-5.6-sol` | 98% | 0 | 1 | 100% | $0.229 | $0.405 |
| `anthropic/claude-opus-4.8` | **100%** | 0 | 0 | 95% | $0.341 | $0.582 |

The three 98% models each miss exactly one field — the *same* one (invoice_07's PO). No
consensus hallucinations from any model.

## The only real issue: `po_reference` (all 15 failures)

The golden set pairs **traps** (a plausible supplier code is present, correct answer is
`null`) with **real POs** (must extract):

| Invoice | Gold | Type | Distractor / note |
|---|---|---|---|
| invoice_02 | `null` | trap | `K-77441` (Kundennummer), `LS-2026-441` (Lieferschein) |
| invoice_04 | `null` | trap | explicit empty ("Reference —") |
| invoice_08 | `null` | trap | `AU-2026-4773` (Auftragsnummer) |
| invoice_03 | `PO-44530` | real PO | labeled "PO #" |
| invoice_05 | `PO-44545` | real PO | German "Bestell-Nr." |
| invoice_07 | `PO-44561` | real PO | **the scanned/image-only invoice** |

The 15 failures split into two sides of one axis — *deciding when the field is empty:*

- **5 hallucinations — invent a value when the field is absent.** All on the null-traps:
  invoice_08 `AU-2026-4773` (haiku OCR + vision, luna vision) and invoice_02 `K-77441`
  (haiku vision, luna OCR). **This is the core failure mode.** (invoice_04's trap fooled
  no one — its PO field is explicitly blank.)
- **10 misses — abstain when a value exists.** The over-correction, concentrated on
  invoice_07's scanned PO (plus a couple of lone vision abstentions on invoice_03/05).

Detection is not involved in any of these — the values are all read correctly elsewhere;
the field is simply hard to call empty-vs-present.

## What consensus actually is: a two-read hallucination filter

Consensus runs the extraction a second, independent way (OCR + a partner view) and keeps a
value only when both reads agree. A hallucination is one read inventing something the other
didn't see → the reads disagree → it's dropped. That's the whole mechanism — a
second-opinion filter on invented values, **not** a detection improvement:

- **All 5 trap hallucinations → 0 at consensus.** haiku and luna each hallucinate the PO
  in 2–3 single views, yet finish at 100% because the partner abstained.
- **The cost is recall.** When a *real* value is confidently read by only one view,
  requiring agreement drops it too. `sonnet-5` on invoice_07 is the clean example: vision
  read `PO-44561` correctly, OCR abstained → they disagreed → consensus discarded a correct
  value. (For terra/sol, both views abstained on that PO, so there was nothing to keep.)

So consensus buys **precision** (removes the hallucinations that are the real risk) at a
small **recall** cost (drops single-view-only real values). On this set that's a good
trade: hallucinating a wrong PO is worse than abstaining on a present one.

## Recommendation

`po_reference` drives no triage decision, and every decision-relevant field is 100% for
every model — so the choice is pure cost. **`luna` and `haiku` hit 100% consensus for
$0.05–0.08**, their single-view hallucinations all filtered out by the second read.
`opus-4.8` is the only model with zero hallucinations even at the single-view level (never
needs consensus to save it), but at ~10× the cost.
