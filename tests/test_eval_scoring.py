"""Lead-scoring eval.

Offline layer validates the heuristic tier banding on the labeled prospect set;
the critical invariant is that ICP fabricators are NEVER disqualified. Live layer
(@pytest.mark.eval) checks the model-scored tier precision against the target.
"""
from __future__ import annotations

import csv
import os
from pathlib import Path

import pytest

from constrox_sdr.state import Prospect, ICPSegment
from constrox_sdr.nodes.scoring import score_prospect_heuristic

DATA = Path(__file__).resolve().parent.parent / "eval" / "prospects_labeled.csv"
HAS_KEY = bool(os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("ANTHROPIC_API_KEY"))

_SEGMENTS = ("fabricator", "gc", "consultancy", "precast_rebar")


def _prospect(row) -> Prospect:
    seg = row["segment"] if row["segment"] in _SEGMENTS else "other"
    jur = row["jurisdiction"] if row["jurisdiction"] in ("US", "UK", "AU") else None
    return Prospect(lead_id="x", company=row["company"], title=row["title"],
                    icp_segment=seg, jurisdiction=jur,
                    firmographics={"size": row.get("size", "")})


def _rows():
    with open(DATA, newline="") as f:
        return list(csv.DictReader(f))


def _sampled(rows):
    """Optionally subsample (evenly spaced) to stay within free-tier API quota.
    Set EVAL_SAMPLE=N to evaluate N rows; EVAL_SLEEP=secs to pace calls."""
    n = int(os.getenv("EVAL_SAMPLE", "0") or 0)
    if n and n < len(rows):
        step = len(rows) / n
        rows = [rows[int(i * step)] for i in range(n)]
    return rows


def test_dataset_has_tier_spread():
    rows = _rows()
    tiers = {r["expected_tier"] for r in rows}
    assert {"A", "B", "disqualify"} <= tiers
    assert len(rows) >= 25


def test_fabricators_never_disqualified_offline():
    """The most important scoring invariant: do not throw away high-intent ICP."""
    for r in _rows():
        if r["segment"] == "fabricator":
            assert score_prospect_heuristic(_prospect(r)).tier != "disqualify", r["company"]


def test_heuristic_tier_accuracy_offline():
    rows = _rows()
    correct = sum(1 for r in rows if score_prospect_heuristic(_prospect(r)).tier == r["expected_tier"])
    acc = correct / len(rows)
    assert acc >= 0.70, f"heuristic tier accuracy regressed: {acc:.2f}"


@pytest.mark.eval
@pytest.mark.skipif(not HAS_KEY, reason="no LLM API key set")
def test_llm_scoring_precision():
    import time
    from constrox_sdr import models
    from constrox_sdr.state import LeadScore
    rows = _sampled(_rows())
    sleep = float(os.getenv("EVAL_SLEEP", "0") or 0)
    correct = 0
    fabricator_dq = 0
    for r in rows:
        p = _prospect(r)
        prompt = (
            "Score this prospect for an offshore steel-detailing/BIM/estimation service. "
            "Return fit, intent (0-100) and a tier (A/B/C/disqualify). Steel fabricators are "
            "highest intent; off-ICP (e.g. bakery, law firm, software startup) = disqualify.\n\n"
            f"Company: {r['company']} | Title: {r['title']} | Segment: {r['segment']} | "
            f"Geo: {r['jurisdiction']} | Size: {r.get('size','')}"
        )
        try:
            sc: LeadScore = models.structured("score", LeadScore).invoke(prompt)
        except Exception as e:
            if any(k in str(e) for k in ("RESOURCE_EXHAUSTED", "429", "quota")):
                pytest.skip(f"LLM quota exhausted — rerun on fresh quota / paid tier: {str(e)[:80]}")
            raise
        correct += int(sc.tier == r["expected_tier"])
        if r["segment"] == "fabricator" and sc.tier == "disqualify":
            fabricator_dq += 1
        if sleep:
            time.sleep(sleep)
    acc = correct / len(rows)
    assert fabricator_dq == 0, "LLM disqualified an ICP fabricator"
    assert acc >= 0.80, f"LLM tier precision below target: {acc:.2f}"
