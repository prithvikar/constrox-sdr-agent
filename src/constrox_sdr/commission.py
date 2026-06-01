"""Commission engine + pipeline math (async side-loop, keyed by deal_id).

Commission is **recurring on paid invoice**: every monthly paid invoice for a
recurring deal re-fires a fresh commission row. One-off project packages fire a
single commission on their (one) paid invoice. Rates are config-tunable.

This is intentionally outside ``SalesState`` (see state.py docstring): it is an
event-driven side-loop fed by a billing ``invoice.paid`` webhook, not part of
the linear prospect thread.
"""
from __future__ import annotations

from typing import Iterable, Optional

from . import config

# Deal stages considered "open pipeline" (not yet won/lost).
_OPEN_STAGES = frozenset({"open", "discovery", "demo", "negotiation"})
# Stages that count as a qualified opportunity (advanced past initial "open").
_QUALIFIED_STAGES = frozenset({"discovery", "demo", "negotiation", "won", "lost"})


# --------------------------------------------------------------------------- #
# Rate tiering                                                                 #
# --------------------------------------------------------------------------- #
def tier_rate(monthly_basis: float, recurring: bool) -> float:
    """Resolve the commission rate for a paid invoice.

    - recurring retainer with monthly basis >= threshold -> premium rate (13%)
    - any other recurring retainer                        -> recurring rate (10%)
    - one-off project package                             -> one-off rate (7%)
    """
    if recurring and monthly_basis >= config.COMMISSION_PREMIUM_MONTHLY_THRESHOLD:
        return config.COMMISSION_RECURRING_PREMIUM_RATE
    if recurring:
        return config.COMMISSION_RECURRING_RATE
    return config.COMMISSION_ONEOFF_RATE


# --------------------------------------------------------------------------- #
# In-memory ledger                                                            #
# --------------------------------------------------------------------------- #
class CommissionLedger:
    """Deterministic in-memory store for deals, invoices, and commissions.

    Mirrors the Postgres tables in db/schema.sql. The real implementation swaps
    these dicts for SQL writes behind the same method surface.
    """

    def __init__(self) -> None:
        self.deals: dict[str, dict] = {}
        self.invoices: dict[str, dict] = {}
        self.commissions: dict[str, dict] = {}

    # -- deals ------------------------------------------------------------- #
    def upsert_deal(self, deal: dict) -> str:
        did = deal.get("deal_id") or f"deal-{len(self.deals) + 1}"
        self.deals[did] = {**self.deals.get(did, {}), **deal, "deal_id": did}
        return did

    def deal(self, deal_id: str) -> Optional[dict]:
        return self.deals.get(deal_id)

    # -- invoices ---------------------------------------------------------- #
    def upsert_invoice(self, invoice: dict) -> str:
        iid = invoice.get("invoice_id") or f"inv-{len(self.invoices) + 1}"
        self.invoices[iid] = {**self.invoices.get(iid, {}), **invoice, "invoice_id": iid}
        return iid

    # -- commissions ------------------------------------------------------- #
    def insert_commission(
        self,
        deal_id: str,
        invoice_id: str,
        rate: float,
        basis_amount: float,
        recurring_schedule: str = "monthly",
    ) -> dict:
        cid = f"comm-{len(self.commissions) + 1}"
        record = {
            "commission_id": cid,
            "deal_id": deal_id,
            "invoice_id": invoice_id,
            "rate": rate,
            "basis_amount": basis_amount,
            "commission_amount": round(rate * basis_amount, 2),
            "recurring_schedule": recurring_schedule,
        }
        self.commissions[cid] = record
        return record

    # -- event handler ----------------------------------------------------- #
    def on_invoice_paid(self, event: dict) -> Optional[dict]:
        """Handle a billing ``invoice.paid``-style event.

        Always upserts the invoice. If the invoice is not paid, returns None.
        Otherwise computes the rate from the parent deal's ``recurring`` flag and
        records a commission. Recurring deals re-fire a fresh commission row on
        every monthly paid invoice (idempotency is keyed on invoice_id upstream
        by the webhook layer; here each distinct paid invoice yields one row).
        """
        invoice_id = self.upsert_invoice(event)
        if event.get("status") != "paid":
            return None

        deal_id = event["deal_id"]
        deal = self.deals.get(deal_id, {})
        recurring = bool(deal.get("recurring", False))
        basis_amount = float(event["amount"])
        rate = tier_rate(basis_amount, recurring)
        return self.insert_commission(
            deal_id=deal_id,
            invoice_id=invoice_id,
            rate=rate,
            basis_amount=basis_amount,
            recurring_schedule="monthly" if recurring else "one_time",
        )


# --------------------------------------------------------------------------- #
# Pipeline math helpers                                                        #
# --------------------------------------------------------------------------- #
def pipeline_value(deals: Iterable[dict]) -> float:
    """Sum of monthly pipeline_value across all open-stage deals."""
    return float(
        sum(
            float(d.get("pipeline_value", 0.0) or 0.0)
            for d in deals
            if d.get("stage") in _OPEN_STAGES
        )
    )


def coverage_ratio(deals: Iterable[dict], target: float = config.MONTHLY_REVENUE_TARGET) -> float:
    """Open pipeline value as a multiple of the monthly revenue target."""
    deals = list(deals)
    if target <= 0:
        return 0.0
    return pipeline_value(deals) / target


def conversion_rate(deals: Iterable[dict]) -> float:
    """Won deals / qualified deals (advanced past the initial 'open' stage)."""
    deals = list(deals)
    qualified = [d for d in deals if d.get("stage") in _QUALIFIED_STAGES]
    if not qualified:
        return 0.0
    won = sum(1 for d in qualified if d.get("stage") == "won")
    return won / len(qualified)


def meets_coverage(deals: Iterable[dict]) -> bool:
    """True when open pipeline coverage is at or above the required multiple."""
    return coverage_ratio(deals) >= config.PIPELINE_COVERAGE_MULTIPLE
