"""Reply-classification eval.

Offline layer (always runs): validates the labeled dataset + heuristic wiring.
Live layer (@pytest.mark.eval): runs the real model (Gemini by default) and
asserts the design target (>=0.85 intent accuracy). Skips without an API key.
"""
from __future__ import annotations

import csv
import os
from pathlib import Path

import pytest

from constrox_sdr.state import ReplyClass
from constrox_sdr.nodes.reply import classify_reply_heuristic

DATA = Path(__file__).resolve().parent.parent / "eval" / "replies_labeled.csv"
HAS_KEY = bool(os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("ANTHROPIC_API_KEY"))


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


def test_dataset_covers_all_intents():
    rows = _rows()
    intents = {r["intent"] for r in rows}
    expected = {"interested", "not_interested", "objection", "referral",
                "ooo_autoreply", "unsubscribe", "meeting_request"}
    assert expected <= intents, f"missing intents: {expected - intents}"
    assert len(rows) >= 50


def test_dataset_covers_all_objection_types():
    rows = _rows()
    otypes = {r["objection_type"] for r in rows if r["intent"] == "objection" and r["objection_type"]}
    expected = {"quality_qa", "code_familiarity", "timezone", "software_compat",
                "liability_ip", "incumbent", "pricing", "trust_references"}
    assert expected <= otypes, f"missing objection types: {expected - otypes}"


def test_heuristic_baseline_offline():
    rows = _rows()
    correct = sum(1 for r in rows if classify_reply_heuristic(r["text"]).intent == r["intent"])
    acc = correct / len(rows)
    assert acc >= 0.55, f"heuristic intent accuracy regressed: {acc:.2f}"


@pytest.mark.eval
@pytest.mark.skipif(not HAS_KEY, reason="no LLM API key set")
def test_llm_classification_accuracy():
    import time
    from constrox_sdr import models
    from constrox_sdr.prompts import reply_classification_prompt
    rows = _sampled(_rows())
    sleep = float(os.getenv("EVAL_SLEEP", "0") or 0)
    correct = 0
    for r in rows:
        try:
            rc: ReplyClass = models.structured("classify_reply", ReplyClass).invoke(
                reply_classification_prompt(r["text"]))
        except Exception as e:
            if any(k in str(e) for k in ("RESOURCE_EXHAUSTED", "429", "quota")):
                pytest.skip(f"LLM quota exhausted — rerun on fresh quota / paid tier: {str(e)[:80]}")
            raise
        correct += int(rc.intent == r["intent"])
        if sleep:
            time.sleep(sleep)
    acc = correct / len(rows)
    assert acc >= 0.85, f"LLM intent accuracy below target: {acc:.2f}"
