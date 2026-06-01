"""Tests for the commission engine + pipeline math (commission.py).

Standalone: imports only constrox_sdr.commission + config, no LLM, no graph.
"""
from __future__ import annotations

from constrox_sdr import config
from constrox_sdr.commission import (
    CommissionLedger,
    conversion_rate,
    coverage_ratio,
    meets_coverage,
    pipeline_value,
    tier_rate,
)


# --------------------------------------------------------------------------- #
# tier_rate boundaries                                                        #
# --------------------------------------------------------------------------- #
def test_tier_rate_oneoff_is_7pct():
    assert tier_rate(25_000.0, recurring=False) == config.COMMISSION_ONEOFF_RATE == 0.07


def test_tier_rate_recurring_below_threshold_is_10pct():
    assert tier_rate(4_000.0, recurring=True) == config.COMMISSION_RECURRING_RATE == 0.10


def test_tier_rate_recurring_at_threshold_is_13pct():
    # boundary: exactly the threshold qualifies for the premium tier
    assert tier_rate(config.COMMISSION_PREMIUM_MONTHLY_THRESHOLD, recurring=True) == 0.13


def test_tier_rate_recurring_above_threshold_is_13pct():
    assert tier_rate(12_000.0, recurring=True) == config.COMMISSION_RECURRING_PREMIUM_RATE == 0.13


def test_tier_rate_high_oneoff_still_7pct():
    # a big one-off project never gets the recurring premium rate
    assert tier_rate(50_000.0, recurring=False) == 0.07


# --------------------------------------------------------------------------- #
# on_invoice_paid                                                             #
# --------------------------------------------------------------------------- #
def test_on_invoice_paid_skips_unpaid_invoice():
    ledger = CommissionLedger()
    ledger.upsert_deal({"deal_id": "d1", "recurring": True, "pipeline_value": 5000.0})

    result = ledger.on_invoice_paid(
        {"invoice_id": "i1", "deal_id": "d1", "amount": 5000.0, "status": "open"}
    )

    assert result is None
    assert ledger.commissions == {}
    # invoice is still recorded even though no commission fired
    assert ledger.invoices["i1"]["status"] == "open"


def test_on_invoice_paid_records_commission():
    ledger = CommissionLedger()
    ledger.upsert_deal({"deal_id": "d1", "recurring": True, "pipeline_value": 10_000.0})

    result = ledger.on_invoice_paid(
        {"invoice_id": "i1", "deal_id": "d1", "amount": 10_000.0, "status": "paid"}
    )

    assert result is not None
    assert result["deal_id"] == "d1"
    assert result["invoice_id"] == "i1"
    assert result["rate"] == 0.13  # recurring >= 8000
    assert result["basis_amount"] == 10_000.0
    assert result["commission_amount"] == 1_300.0
    assert result["recurring_schedule"] == "monthly"
    assert len(ledger.commissions) == 1


def test_on_invoice_paid_oneoff_uses_7pct():
    ledger = CommissionLedger()
    ledger.upsert_deal({"deal_id": "d2", "recurring": False, "pipeline_value": 20_000.0})

    result = ledger.on_invoice_paid(
        {"invoice_id": "i1", "deal_id": "d2", "amount": 20_000.0, "status": "paid"}
    )

    assert result["rate"] == 0.07
    assert result["commission_amount"] == 1_400.0
    assert result["recurring_schedule"] == "one_time"


def test_recurring_deal_refires_each_monthly_paid_invoice():
    ledger = CommissionLedger()
    ledger.upsert_deal({"deal_id": "d1", "recurring": True, "pipeline_value": 9_000.0})

    # month 1
    c1 = ledger.on_invoice_paid(
        {"invoice_id": "i-jun", "deal_id": "d1", "amount": 9_000.0,
         "status": "paid", "period": "2026-06"}
    )
    # month 2 — a NEW paid invoice on the same recurring deal re-fires
    c2 = ledger.on_invoice_paid(
        {"invoice_id": "i-jul", "deal_id": "d1", "amount": 9_000.0,
         "status": "paid", "period": "2026-07"}
    )

    assert c1 is not None and c2 is not None
    assert c1["commission_id"] != c2["commission_id"]
    assert c1["invoice_id"] == "i-jun"
    assert c2["invoice_id"] == "i-jul"
    # two distinct commission rows for the two monthly invoices
    assert len(ledger.commissions) == 2
    assert c1["rate"] == c2["rate"] == 0.13
    assert c1["commission_amount"] == c2["commission_amount"] == 1_170.0


# --------------------------------------------------------------------------- #
# pipeline math                                                               #
# --------------------------------------------------------------------------- #
def _sample_deals_hitting_3x():
    # MONTHLY_REVENUE_TARGET is 30_000 -> need >= 90_000 open pipeline for 3x.
    return [
        {"deal_id": "a", "stage": "discovery", "pipeline_value": 40_000.0},
        {"deal_id": "b", "stage": "demo", "pipeline_value": 30_000.0},
        {"deal_id": "c", "stage": "negotiation", "pipeline_value": 25_000.0},
        {"deal_id": "d", "stage": "won", "pipeline_value": 12_000.0},   # not open
        {"deal_id": "e", "stage": "lost", "pipeline_value": 9_000.0},   # not open
    ]


def test_pipeline_value_only_counts_open_stages():
    deals = _sample_deals_hitting_3x()
    # 40k + 30k + 25k = 95k (won/lost excluded)
    assert pipeline_value(deals) == 95_000.0


def test_coverage_ratio_and_meets_coverage_at_3x():
    deals = _sample_deals_hitting_3x()
    ratio = coverage_ratio(deals)
    assert ratio == 95_000.0 / config.MONTHLY_REVENUE_TARGET
    assert ratio >= config.PIPELINE_COVERAGE_MULTIPLE
    assert meets_coverage(deals) is True


def test_meets_coverage_false_when_thin():
    deals = [
        {"deal_id": "a", "stage": "discovery", "pipeline_value": 20_000.0},
        {"deal_id": "b", "stage": "demo", "pipeline_value": 10_000.0},
    ]
    assert pipeline_value(deals) == 30_000.0
    assert coverage_ratio(deals) == 1.0
    assert meets_coverage(deals) is False


def test_conversion_rate_won_over_qualified():
    deals = _sample_deals_hitting_3x()  # 5 qualified (past open), 1 won
    assert conversion_rate(deals) == 1 / 5


def test_conversion_rate_zero_when_no_qualified():
    deals = [{"deal_id": "a", "stage": "open", "pipeline_value": 5_000.0}]
    assert conversion_rate(deals) == 0.0
