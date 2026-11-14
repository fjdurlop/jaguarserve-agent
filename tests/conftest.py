"""Offline fixtures: demo catalog in memory, mock calendar (fixed clock), fake search, scripted LLM."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent.calendar.mock import MockCalendar
from agent.catalog.memory import MemoryCatalog
from agent.config import Settings
from agent.embeddings import HashEmbedder
from agent.llm import Reply, ToolCall
from agent.loop import Deps
from agent.search import WebSearch
from ingest import load_catalog

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "data" / "demo_catalog"
NOW = datetime(2026, 11, 16, 8, 0, tzinfo=UTC)  # a Monday


class ScriptedLLM:
    """Returns pre-written replies in order; records the messages it was called with."""

    name = "scripted"

    def __init__(self, replies: list[Reply], is_ready: bool = True):
        self.replies = list(replies)
        self.calls: list[list[dict]] = []
        self.is_ready = is_ready

    async def ready(self) -> bool:
        return self.is_ready

    async def stream(self, messages, tools):
        self.calls.append(list(messages))
        reply = self.replies.pop(0) if self.replies else Reply(content="(no more replies)")
        if reply.content and not reply.tool_calls:
            yield "token", reply.content
        yield "reply", reply


def call(tool: str, cid: str = "c1", /, **args) -> Reply:
    return Reply(tool_calls=[ToolCall(cid, tool, json.dumps(args))])


def answer(text: str) -> Reply:
    return Reply(content=text)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        store="memory",
        embedding_model="hash",
        search_provider="fake",
        search_allow_list="example.org,example.com",
        timezone="UTC",
        llm_ready_timeout=0.2,
        internal_tokens="staff-token",
        privacy_notice_url="https://example.org/privacy",
    )


@pytest.fixture
def store() -> MemoryCatalog:
    s = MemoryCatalog(HashEmbedder())
    load_catalog(CATALOG, s)
    return s


@pytest.fixture
def calendar(settings) -> MockCalendar:
    return MockCalendar(
        settings.appointment_type_list,
        settings.business_hours,
        settings.timezone,
        settings.slot_minutes,
        settings.booking_lead_hours,
        now=lambda: NOW,
    )


@pytest.fixture
def web(settings) -> WebSearch:
    return WebSearch("fake", settings.allow_list)


@pytest.fixture
def make_deps(settings, store, calendar, web):
    def _make(replies: list[Reply], ready: bool = True) -> Deps:
        return Deps(settings, store, calendar, web, ScriptedLLM(replies, ready))

    return _make
