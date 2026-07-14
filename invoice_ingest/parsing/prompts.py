from __future__ import annotations

# The po_reference rule, interpolated into _CONTRACT below. Two versions — exactly one
# must be live. Swap by commenting one out and uncommenting the other.

# LIVE. Generic: a PO is the buyer's number. Names no label, so it transfers to
# distractors we have never seen.
_PO_RULE = """the customer's (buyer's) purchase order reference — the number the \
buyer issued to order these goods, not a number the supplier issued. Return null if no \
buyer PO is present."""

# DISABLED — overfits the golden set. This version makes every model pass invoice_08
# (which they otherwise fail, reading its "Auftragsnummer: AU-2026-4773" as the PO), but
# it does that by naming that invoice's own distractor labels: it buys eval points
# without making the extractor any better on an invoice we have not already labeled.
# Re-enable only as a deliberate domain lexicon, scored on invoices it was NOT written
# from — never to make the golden-set number look good.
# _PO_RULE = """the customer's (buyer's) purchase order reference. Disqualify a number \
# only when it is the SUPPLIER's own — e.g. Auftragsnummer (the supplier's order/job \
# number), Lieferschein (delivery note), or Kundennummer (customer account number). \
# Judge by whose number it is, not by the label wording: a field labelled like an order \
# number can still be the buyer's PO. Return null if no buyer PO is present."""

# Field contract + grounding + normalization rules, shared verbatim across prompts.
_CONTRACT = f"""Ground every answer in the input you are given: use ONLY information \
explicitly present there. Do not use outside knowledge, do not guess, and do not \
infer values that are not written.

Extract a field only when you are certain — both that you read the value correctly \
AND that it is the right value for that field. If there is any doubt, return null. \
Null is always an acceptable answer; a wrong value is not. You are not rewarded for \
filling fields.

Read label + value, not value alone. A value counts only if the surrounding text — \
its label or heading — states what it is, and that meaning matches the field. Never \
select a value just because it looks like the right kind (a date, an amount, a \
reference code). If the document shows several candidates for a field and their \
labels do not clearly single one out, that is doubt: return null.

Judge meaning from the document's own wording, in its language. If a label is \
ambiguous about whose number/date/amount it is (the supplier's or the customer's), \
treat the field as absent rather than assuming.

For every field return:
  - value: the normalized value taken only from the input, or null if the field is \
absent or you are unsure. Never invent a value to fill the schema.
  - source_quote: text copied VERBATIM from the input the value was read from \
(character-for-character). Empty string when value is null.

Field meanings and normalization:
  - amount: the grand total payable INCLUDING VAT — not the subtotal, not the VAT \
line — as a decimal number, e.g. 1234.56.
  - currency: one of DKK, EUR, or USD.
  - invoice_date / due_date: an ISO date, YYYY-MM-DD.
  - invoice_id: the supplier's invoice number — not an order, delivery, or shipping \
reference.
  - po_reference: {_PO_RULE}
Invoices may be in Danish, German, or English."""

# One exact prompt per agent, written for its specific input.
OCR_PROMPT = f"""You extract structured data from the OCR text of a single \
supplier invoice. This text was produced by optical character recognition of the \
scanned page, so it may contain recognition errors — confused digits (8/B, 0/O, \
1/l), swapped decimal/thousands separators, and broken table columns. Read \
carefully and prefer values that are internally consistent.

{_CONTRACT}"""

TEXT_PROMPT = f"""You extract structured data from the embedded PDF text layer of \
a single supplier invoice. The characters are exact (no OCR errors), but the \
reading order can be jumbled where the PDF draws multi-column tables — labels and \
their values may be separated. Match each value to its correct label.

{_CONTRACT}"""

VISION_PROMPT = f"""You extract structured data from the page image(s) of a single \
supplier invoice. Read the invoice visually, as a person would: use the layout, \
table structure, and positioning to tell labels from values and to distinguish the \
subtotal, VAT, and grand total. Transcribe each source_quote as the exact text \
visible in the image.

{_CONTRACT}"""
