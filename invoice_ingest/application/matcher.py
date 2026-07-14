#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import logging
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from rapidfuzz import fuzz

from invoice_ingest import config
from invoice_ingest.shared.compare import _norm_id, _norm_text, cmp_amount
from invoice_ingest.shared.reconcile import build_consensus, load_records

logger = logging.getLogger(__name__)

# Payment date should fall within this many days of the invoice/due window.
DATE_WINDOW_DAYS = 7
# Counterparty fuzzy score (0-100): STRONG = confidently the same entity; LOOSE =
# weak but worth surfacing as a candidate (bank names are heavily truncated). A hit
# between the two is a real but low-confidence identity — it can't auto-accept on
# its own, only corroborate.
NAME_STRONG = 80
NAME_LOOSE = 55
# Match (identity) bands.
MATCH_MIN = 50            # below this we can't confidently identify a payment → reject
MATCH_ACCEPT_MIN = 95     # at/above (with a clean reconcile): eligible for auto-accept
# Approval (reconcile) score weights. Amount is primary and must be EXACT to earn
# full credit; the date supports. A benign mismatch (fx/batch/discount) is a known,
# expected difference — it earns PARTIAL amount credit rather than zero, so an FX
# payment doesn't look like a reconciliation failure. Auto-accept still needs a
# perfect 100 (exact amount + date), so partial credit can never auto-approve.
AMOUNT_WEIGHT = 70
DATE_WEIGHT = 30
BENIGN_AMOUNT_CREDIT = 0.5
APPROVAL_ACCEPT_MIN = 100
# Fields that must be trustworthy to reconcile at all.
CRITICAL_FIELDS = ("invoice_id", "amount", "supplier_name", "currency")


# --------------------------------------------------------------------------- IO

def load_bank(path: Path) -> list[dict]:
    """Bank transactions with amount parsed to a positive Decimal and date to date."""
    txns = []
    for row in csv.DictReader(path.open(encoding="utf-8")):
        try:
            row["amount_dkk"] = abs(Decimal(row["amount"]))
        except (InvalidOperation, KeyError):
            row["amount_dkk"] = None
        row["date_obj"] = date.fromisoformat(row["date"]) if row.get("date") else None
        txns.append(row)
    return txns


def _val(consensus: dict, field: str):
    return consensus["extraction"][field]["value"]


# ----------------------------------------------------------------------- match

def counterparty_score(supplier: str, counterparty: str) -> float:
    """Fuzzy similarity between a supplier name and a bank counterparty (0-100)."""
    return fuzz.WRatio(_norm_text(supplier), _norm_text(counterparty))


def find_match(consensus: dict, txns: list[dict]) -> dict | None:
    """Best matching transaction by (exact reference OR fuzzy counterparty).

    Ranking: a reference hit wins over a name-only hit; then higher name score;
    then closer amount. Returns the match with its signals, or None.
    """
    inv_id = _val(consensus, "invoice_id")
    supplier = _val(consensus, "supplier_name")
    amount = _val(consensus, "amount")

    best: dict | None = None
    best_key: tuple[bool, float, float] | None = None
    for txn in txns:
        ref_match = bool(inv_id) and _norm_id(inv_id) in _norm_id(txn["reference"])
        name_score = counterparty_score(supplier, txn["counterparty"]) if supplier else 0.0
        # Surface anything with a reference hit or even a loose name — the graded
        # confidence downstream decides whether it's trustworthy.
        if not (ref_match or name_score >= NAME_LOOSE):
            continue

        amount_gap = _amount_gap(amount, txn["amount_dkk"])
        key = (ref_match, name_score, -amount_gap)  # higher is better
        if best_key is None or key > best_key:
            best_key = key
            best = {"txn": txn, "ref_match": ref_match, "name_score": name_score}
    return best


def _amount_gap(amount, bank_amount) -> float:
    """Absolute distance between invoice amount and a bank amount (for tie-breaks)."""
    try:
        return float(abs(Decimal(str(amount)) - bank_amount))
    except (InvalidOperation, TypeError):
        return float("inf")


# ----------------------------------------------------------------------- score

def amount_exact(consensus: dict, txn: dict) -> bool:
    """Invoice amount == bank amount. Only comparable when the invoice is in DKK
    (the bank is always DKK); a foreign-currency invoice was paid via FX."""
    amount, currency = _val(consensus, "amount"), _val(consensus, "currency")
    if amount is None or txn["amount_dkk"] is None or (currency and currency != "DKK"):
        return False
    return cmp_amount(amount, str(txn["amount_dkk"]))


def _parse_date(value: str | None) -> date | None:
    """Parse an ISO date, or None if absent/unparseable."""
    try:
        return date.fromisoformat(value or "")
    except ValueError:
        return None


def date_ok(consensus: dict, txn: dict) -> bool:
    """Bank date falls within the invoice→due window (± a grace period).

    Each date is parsed independently, so one missing date doesn't discard the
    other: with only one present, it acts as both ends of the window.
    """
    bank_date = txn["date_obj"]
    if bank_date is None:
        return False
    inv = _parse_date(_val(consensus, "invoice_date"))
    due = _parse_date(_val(consensus, "due_date"))
    lo, hi = inv or due, due or inv
    if lo is None or hi is None:
        return False
    grace = timedelta(days=DATE_WINDOW_DAYS)
    return lo - grace <= bank_date <= hi + grace


def extraction_issues(consensus: dict) -> list[str]:
    """Critical fields that aren't trustworthy (missing / disagreed / ungrounded)."""
    issues = []
    for field in CRITICAL_FIELDS:
        fv = consensus["extraction"][field]
        if fv["value"] is None:
            issues.append(f"{field} missing")
        elif fv.get("agreement") is False:
            issues.append(f"{field} disagreement")
        elif fv.get("quote_found") is False:
            issues.append(f"{field} ungrounded")
    return issues


def diagnose_amount(consensus: dict, txn: dict) -> tuple[str, str]:
    """Classify why an amount doesn't match: (category, human reason).

    category ∈ {fx, batch, discount, unexplained}. The first three are benign,
    known reasons the invoice amount legitimately differs from the DKK payment; an
    `unexplained` mismatch on a confidently-matched invoice is a data-integrity red
    flag (the bank paid a different amount for no visible reason).
    """
    currency = _val(consensus, "currency")
    if currency and currency != "DKK":
        return "fx", f"{currency} invoice paid in DKK — amount not directly comparable (FX)"
    ref = txn["reference"]
    if "+" in ref:
        return "batch", (f"amount mismatch: invoice {_val(consensus,'amount')} vs bank "
                         f"{txn['amount_dkk']} — reference lists several invoices (batch payment)")
    if any(k in ref.lower() for k in ("-2%", "discount", "early", "rabat")):
        return "discount", (f"amount mismatch: invoice {_val(consensus,'amount')} vs bank "
                            f"{txn['amount_dkk']} — reference notes an early-payment discount")
    return "unexplained", (f"amount mismatch: invoice {_val(consensus,'amount')} vs bank "
                          f"{txn['amount_dkk']} — no explanation (data-integrity)")


# ---------------------------------------------------------------------- triage

def match_score(ref_match: bool, name_score: float) -> int:
    """MATCH score (0-100): how sure are we WHICH transaction this is? (identity)

    Two independent signals — the exact invoice-id in the bank reference (the
    stronger, 60) and the fuzzy company↔counterparty match (up to 40, scaled by its
    score). A confident identity needs both to agree; one alone caps it well below
    100 (e.g. exact reference + a bank name too truncated to score → ~85, not 100).
    """
    return round(60 * ref_match + 0.40 * name_score)


def approval_score(amount_exact: bool, amount_category: str | None, date_ok: bool) -> int:
    """APPROVAL score (0-100): does the matched payment check out? (reconciliation)

    Amount is the decisive part; it must be EXACT for full credit. A benign mismatch
    (fx/batch/discount — a known, expected difference) earns partial credit; an
    unexplained mismatch earns none. The date supports. Separate from identity: an
    invoice can be the right payment (high match) yet not fully reconcile (e.g. FX).
    """
    if amount_exact:
        amount = AMOUNT_WEIGHT
    elif amount_category in ("fx", "batch", "discount"):
        amount = round(AMOUNT_WEIGHT * BENIGN_AMOUNT_CREDIT)
    else:  # unexplained mismatch, or no amount at all
        amount = 0
    return amount + (DATE_WEIGHT if date_ok else 0)


def _new_result(consensus: dict) -> dict:
    return {
        "invoice_path": consensus["invoice_path"],
        "invoice_id": _val(consensus, "invoice_id"),
        "status": None,
        "match_score": 0,
        "match_reasons": [],
        "approval_score": 0,
        "approval_reasons": [],
        "txn_id": None,
        "signals": {},
    }


def triage(consensus: dict, txns: list[dict]) -> dict:
    """Route one invoice. Two scores drive it: identity (which payment?) and
    reconciliation (does the amount & date check out?). Each score gets its own
    reasons so we can explain the confidence in both concerns."""
    result = _new_result(consensus)
    issues = extraction_issues(consensus)

    # Hard integrity failure — a critical field is missing, nothing to reconcile.
    if _val(consensus, "amount") is None or _val(consensus, "invoice_id") is None:
        result["status"] = "reject"
        result["approval_reasons"] = ["data-integrity: " + ", ".join(issues)]
        result["match_reasons"] = ["cannot identify — critical field missing"]
        return result

    match = find_match(consensus, txns)
    if match is None:
        result["status"] = "review"
        result["match_reasons"] = ["no matching bank transaction (possibly unpaid)"]
        return result

    txn, ref, ns = match["txn"], match["ref_match"], match["name_score"]
    ae, do = amount_exact(consensus, txn), date_ok(consensus, txn)
    amount_category, amount_reason = (None, None) if ae else diagnose_amount(consensus, txn)
    ms = match_score(ref, ns)                            # SCORE 1 — identity
    aps = approval_score(ae, amount_category, do)        # SCORE 2 — reconciliation
    result.update(match_score=ms, approval_score=aps, txn_id=txn["txn_id"],
                  signals={"ref": ref, "name_score": round(ns),
                           "amount_exact": ae, "date_ok": do})

    # --- identity (match) reasons ---
    match_reasons: list[str] = []
    if ref and ns < NAME_STRONG:
        match_reasons.append(f"supplier name weakly matches counterparty ({ns:.0f}/100) "
                             f"— identity rests on the reference alone")
    elif not ref:
        match_reasons.append(f"matched by supplier name only ({ns:.0f}/100), "
                             f"invoice id not in the bank reference")

    # --- reconciliation (approval) reasons ---
    approval_reasons: list[str] = []
    if issues:
        approval_reasons.append("low extraction confidence: " + ", ".join(issues))
    if amount_reason:
        approval_reasons.append(amount_reason)
    if not do:
        approval_reasons.append("payment date outside the expected window")

    # Route on the TWO scores.
    if ms < MATCH_MIN:
        # Couldn't confidently identify a payment at all — don't trust the match.
        result["status"] = "reject"
        match_reasons.insert(0, f"could not confidently identify the payment "
                                f"(match {ms}/100, below {MATCH_MIN})")
    elif ref and amount_category == "unexplained":
        # Confident identity (exact reference) but the amount is wrong for no benign
        # reason — the bank paid something different: a data-integrity failure.
        result["status"] = "reject"
    elif ms >= MATCH_ACCEPT_MIN and aps >= APPROVAL_ACCEPT_MIN and not issues:
        result["status"] = "auto_accept"
        match_reasons = ["identity confirmed (reference + company)"]
        approval_reasons = ["amount and date reconcile exactly"]
    else:
        result["status"] = "review"

    # A confident, clean concern still deserves a positive summary.
    if not match_reasons:
        match_reasons = ["identity confirmed (reference + company)"]
    if not approval_reasons:
        approval_reasons = ["amount and date reconcile exactly"]

    result["match_reasons"] = match_reasons
    result["approval_reasons"] = approval_reasons
    return result


def triage_all(consensus: list[dict], txns: list[dict]) -> list[dict]:
    """Triage every invoice, sorted by path for stable output."""
    return [triage(c, txns) for c in sorted(consensus, key=lambda c: c["invoice_path"] or "")]


# ------------------------------------------------------------------------- CLI

def _sig(signals: dict) -> str:
    if not signals:
        return ""
    return (
        f"ref={'Y' if signals['ref'] else '·'} "
        f"name={signals['name_score']:>3} "
        f"amount={'Y' if signals['amount_exact'] else '·'} "
        f"date={'Y' if signals['date_ok'] else '·'}"
    )


def print_triage(results: list[dict]) -> dict[str, int]:
    """Print each invoice's decision + reasons; return the status counts."""
    counts = {"auto_accept": 0, "review": 0, "reject": 0}
    for r in results:
        counts[r["status"]] += 1
        name = Path(r["invoice_path"]).stem
        print(f"\n{name}  [{r['invoice_id']}]  →  {r['status'].upper()}")
        print(f"  match {r['match_score']:>3}/100 (identity)   "
              f"approval {r['approval_score']:>3}/100 (reconcile)   "
              f"txn: {r['txn_id'] or '—'}")
        if r["signals"]:
            print(f"      {_sig(r['signals'])}")
        for reason in r["match_reasons"]:
            print(f"  · [match]    {reason}")
        for reason in r["approval_reasons"]:
            print(f"  · [approval] {reason}")
    return counts


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--extractions", default="extractions.jsonl")
    p.add_argument("--bank", default="input/bank_transactions.csv")
    p.add_argument("--out", default="triage.jsonl", help="Write per-invoice results")
    return p.parse_args()


def main() -> int:
    config.setup_logging()
    args = parse_args()
    consensus = build_consensus(load_records(Path(args.extractions)))
    txns = load_bank(Path(args.bank))
    results = triage_all(consensus, txns)

    with Path(args.out).open("w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    counts = print_triage(results)  # the triage table -> stdout (the deliverable)
    logger.info("wrote %s  (%d auto-accept, %d review, %d reject)", args.out,
                counts["auto_accept"], counts["review"], counts["reject"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
