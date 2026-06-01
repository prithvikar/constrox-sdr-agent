"""Checkpointer factory.

Dev uses an in-memory saver; prod uses Postgres (extra `prod`). Both are
configured with a serializer that allow-lists our Pydantic state types
(Prospect, LeadScore, ...) so they round-trip through the checkpoint without
the unregistered-type warning / future block.
"""
from __future__ import annotations

import os
from typing import Optional

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from .state import BANT, ComplianceResult, LeadScore, Prospect, ReplyClass

# Pydantic models we persist inside SalesState — allow-listed so they round-trip
# through the checkpoint as their real types (not bare dicts) on resume.
ALLOWED_STATE_TYPES = (Prospect, LeadScore, ReplyClass, BANT, ComplianceResult)


def make_serde() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=ALLOWED_STATE_TYPES)


def memory_checkpointer():
    from langgraph.checkpoint.memory import MemorySaver
    return MemorySaver(serde=make_serde())


def postgres_checkpointer(db_url: Optional[str] = None):
    """Construct a Postgres checkpointer (requires the `prod` extra).

    Returns a context manager per langgraph-checkpoint-postgres; caller runs
    `.setup()` once. Kept import-local so dev never needs psycopg.
    """
    from langgraph.checkpoint.postgres import PostgresSaver
    url = db_url or os.environ["DB_URL"]
    return PostgresSaver.from_conn_string(url, serde=make_serde())


def get_checkpointer(prod: bool = False):
    return postgres_checkpointer() if prod else memory_checkpointer()
