"""Thin @tool wrappers over enrichment + CRM, for optional ReAct-style use.

These are *not* required by the linear graph — nodes call adapters directly via
`Deps`. They exist so an agentic node (or a future ReAct planner) can bind a few
safe, read/log-only tools.

Deps are set once at runtime via `set_tool_deps(deps)`; importing this module has
no side effects and does not require any adapter or API key. Calling a tool
before `set_tool_deps` raises a clear error.
"""
from __future__ import annotations

from typing import Optional

from langchain_core.tools import tool

from .adapters.base import Deps

# Module-level dependency handle, injected at runtime.
_DEPS: Optional[Deps] = None


def set_tool_deps(deps: Deps) -> None:
    """Bind the Deps bundle the @tool functions will use. Call once at startup."""
    global _DEPS
    _DEPS = deps


def _require_deps() -> Deps:
    if _DEPS is None:
        raise RuntimeError(
            "Tool dependencies not set. Call constrox_sdr.tools.set_tool_deps(deps) "
            "before invoking any tool."
        )
    return _DEPS


@tool
def enrich_company(domain: str) -> dict:
    """Look up firmographic data for a company by its web domain.

    Returns size, industry, ICP segment, and (where available) jurisdiction —
    useful for research and lead scoring. Read-only.
    """
    deps = _require_deps()
    return deps.enrich.company(domain)


@tool
def find_contact(name: str, company: str) -> dict:
    """Find a contact's work details (email, phone, title, LinkedIn URL) by name
    and company. Read-only; does not send anything."""
    deps = _require_deps()
    return deps.enrich.contact(name, company)


@tool
def crm_log(lead_id: str, note: str) -> str:
    """Append a free-text activity note to a lead's CRM timeline.

    Use to record research findings, call/email outcomes, or next steps. Returns
    a short confirmation string.
    """
    deps = _require_deps()
    deps.crm.log_activity(lead_id, {"type": "note", "note": note})
    return f"logged note to lead {lead_id}"
