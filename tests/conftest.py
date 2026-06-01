"""Shared fixtures: mock adapters, fake LLMs, sample prospects, graph builder.

The fake LLM layer monkeypatches `constrox_sdr.models.llm` / `.structured` so the
whole graph runs deterministically with no API calls. Tests can override the
canned outputs via the `llm_canned` fixture before building the graph.
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from constrox_sdr import models
from constrox_sdr.config import ORG
from constrox_sdr.state import LeadScore, ReplyClass, BANT, Prospect, initial_state
from constrox_sdr.adapters.mock import mock_deps


# --------------------------------------------------------------------------- #
# Fake LLM plumbing                                                            #
# --------------------------------------------------------------------------- #
class _FakeText:
    def __init__(self, text): self._text = text
    def invoke(self, _x): return AIMessage(content=self._text)


class _FakeStructured:
    def __init__(self, obj): self._obj = obj
    def invoke(self, _x): return self._obj


@pytest.fixture
def llm_canned():
    """Mutable dict of canned structured outputs by schema name. Tests tweak it."""
    return {
        "LeadScore": LeadScore(fit=80, intent=80, tier="B", rationale="fabricator fit"),
        "ReplyClass": ReplyClass(intent="interested", sentiment="positive",
                                 suggested_next="book discovery", confidence=0.95),
        "BANT": BANT(need="overflow steel detailing", budget="approved",
                     authority="owner", timeline="Q3", qualified=True),
    }


@pytest.fixture
def fake_llm(monkeypatch, llm_canned):
    """Patch models.llm / models.structured with deterministic fakes.

    Email/draft text always embeds the org postal address + a one-step opt-out
    so the compliance gate passes for US prospects.
    """
    tail = f" {ORG.name}. ABN {ORG.abn}. {ORG.address}. reaching out because we noticed your publicly listed projects. Reply STOP to opt out."

    def _llm(task, tier=None, temperature=0.3):
        return _FakeText(f"[{task}] Constrox offshore steel detailing capacity.{tail}")

    def _structured(task, schema, tier=None, temperature=0.0):
        return _FakeStructured(llm_canned[schema.__name__])

    monkeypatch.setattr(models, "llm", _llm)
    monkeypatch.setattr(models, "structured", _structured)
    return llm_canned


@pytest.fixture
def deps():
    return mock_deps()


@pytest.fixture
def graph(deps, fake_llm):
    from constrox_sdr.graph import build_graph
    return build_graph(deps)


def cfg(thread_id):
    return {"configurable": {"thread_id": thread_id}}


# --------------------------------------------------------------------------- #
# Sample prospects                                                            #
# --------------------------------------------------------------------------- #
@pytest.fixture
def fabricator_us():
    return Prospect(
        lead_id="L-US-FAB", company="Acme Steel Fabricators", domain="acmesteel.com",
        contact_name="Sam Owner", title="Owner", email="sam@acmesteel.com",
        phone="+12145551234", phone_type="business_landline",
        jurisdiction="US", timezone="America/Chicago", entity_type="company",
        icp_segment="fabricator",
    )


@pytest.fixture
def gc_uk():
    return Prospect(
        lead_id="L-UK-GC", company="Britannia Construction Ltd", domain="britanniacon.co.uk",
        contact_name="Jane Pre", title="Preconstruction Manager", email="jane@britanniacon.co.uk",
        phone="+442071234567", phone_type="business_landline",
        jurisdiction="UK", timezone="Europe/London", entity_type="company",
        icp_segment="gc",
    )


@pytest.fixture
def init_state():
    return initial_state
