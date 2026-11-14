"""In-memory chat sessions (single agent-api replica).

A session is bound to the role it was created with: a request with a different role gets a new session,
so internal tool results in history can never reach a public user.
"""

import asyncio
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime

from agent.tools import Source

MAX_HISTORY = 40


@dataclass
class Pending:
    id: str
    call_id: str
    args: dict
    slot: datetime
    summary: str


@dataclass
class Session:
    id: str
    role: str
    lang: str = "en"
    history: list[dict] = field(default_factory=list)
    sources: dict[str, Source] = field(default_factory=dict)
    pending: Pending | None = None
    confirmed: dict[str, str] = field(default_factory=dict)  # pending id -> appointment id
    bookings: set[str] = field(default_factory=set)
    last_seen: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def trim(self) -> None:
        """Keep the last messages, starting at a user message so tool call/result pairs stay intact."""
        if len(self.history) <= MAX_HISTORY:
            return
        cut = len(self.history) - MAX_HISTORY
        while cut < len(self.history) and self.history[cut].get("role") != "user":
            cut += 1
        self.history = self.history[cut:]


class Sessions:
    def __init__(self, ttl_minutes: int = 60):
        self.ttl = ttl_minutes * 60
        self._items: dict[str, Session] = {}

    def get_or_create(self, session_id: str | None, role: str) -> Session:
        self.prune()
        s = self._items.get(session_id or "")
        if s is None or s.role != role:
            s = Session(id=secrets.token_urlsafe(16), role=role)
            self._items[s.id] = s
        s.last_seen = time.monotonic()
        return s

    def get(self, session_id: str) -> Session | None:
        return self._items.get(session_id)

    def prune(self) -> None:
        cutoff = time.monotonic() - self.ttl
        for sid in [k for k, v in self._items.items() if v.last_seen < cutoff and not v.lock.locked()]:
            del self._items[sid]

    def __len__(self) -> int:
        return len(self._items)
