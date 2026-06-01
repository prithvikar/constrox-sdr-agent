"""Pure weekly-summary reporting over the commission ledger / deal set.

No I/O: takes either a CommissionLedger or a raw iterable of deal dicts and
returns a plain dict the caller can render, log, or post to Slack.
"""
from __future__ import annotations

from typing import Iterable, Union

from . import config
from .commission import (
    CommissionLedger,
    conversion_rate,
    coverage_ratio,
    meets_coverage,
    pipeline_value,
)

# Stages that count toward the qualified-opportunity tally (advanced past open).
_QUALIFIED_STAGES = frozenset({"discovery", "demo", "negotiation", "won", "lost"})


def weekly_summary(ledger_or_deals: Union[CommissionLedger, Iterable[dict]]) -> dict:
    """Build a weekly pipeline + commission summary.

    Accepts a CommissionLedger (uses its deals + commissions) or a bare iterable
    of deal dicts (commission total then reported as 0.0).
    """
    if isinstance(ledger_or_deals, CommissionLedger):
        deals = list(ledger_or_deals.deals.values())
        commission_earned = round(
            sum(float(c.get("commission_amount", 0.0)) for c in ledger_or_deals.commissions.values()),
            2,
        )
    else:
        deals = list(ledger_or_deals)
        commission_earned = 0.0

    qualified_opps = sum(1 for d in deals if d.get("stage") in _QUALIFIED_STAGES)

    return {
        "open_pipeline": pipeline_value(deals),
        "coverage_ratio": coverage_ratio(deals),
        "coverage_target_met": meets_coverage(deals),
        "conversion_rate": conversion_rate(deals),
        "monthly_commission_earned": commission_earned,
        "qualified_opps": qualified_opps,
        "revenue_target": config.MONTHLY_REVENUE_TARGET,
    }
