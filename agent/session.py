"""Chat sessions: in memory (one agent-api replica, tests) or in Redis (any number of replicas).

A session is bound to the role it was created with: a request with a different role gets a new session,
so internal tool results in history can never reach a public user.

Turn protocol (both stores): `get_or_create` -> `try_lock` -> `get` again under the lock (another replica
may have changed it) -> run the turn -> `save` -> `unlock`. A lock expires on its own after `lock_ttl`,
so a crashed replica cannot block a session for good.
"""

import json
import secrets
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Protocol

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

    def trim(self) -> None:
        """Keep the last messages, starting at a user message so tool call/result pairs stay intact."""
        if len(self.history) <= MAX_HISTORY:
            return
        cut = len(self.history) - MAX_HISTORY
        while cut < len(self.history) and self.history[cut].get("role") != "user":
            cut += 1
        self.history = self.history[cut:]

    # --- serialisation (Redis) ---
    def to_json(self) -> str:
        d = asdict(self)
        d["bookings"] = sorted(self.bookings)
        if self.pending:
            d["pending"]["slot"] = self.pending.slot.isoformat()
        return json.dumps(d, ensure_ascii=False, default=str)

    @classmethod
    def from_json(cls, raw: str | bytes) -> "Session":
        d = json.loads(raw)
        p = d.get("pending")
        return cls(
            id=d["id"],
            role=d["role"],
            lang=d.get("lang", "en"),
            history=d.get("history", []),
            sources={k: Source(**v) for k, v in d.get("sources", {}).items()},
            pending=Pending(**{**p, "slot": datetime.fromisoformat(p["slot"])}) if p else None,
            confirmed=d.get("confirmed", {}),
            bookings=set(d.get("bookings", [])),
        )


def new_session(role: str) -> Session:
    return Session(id=secrets.token_urlsafe(16), role=role)


class SessionStore(Protocol):
    async def get(self, session_id: str) -> Session | None: ...
    async def save(self, session: Session) -> None: ...
    async def try_lock(self, session_id: str) -> str | None: ...
    async def unlock(self, session_id: str, token: str) -> None: ...
    async def close(self) -> None: ...


async def get_or_create(store: SessionStore, session_id: str | None, role: str) -> Session:
    s = await store.get(session_id) if session_id else None
    if s is None or s.role != role:
        s = new_session(role)
        await store.save(s)
    return s


class MemorySessions:
    """Single-process store. Objects are kept as they are (no copy)."""

    def __init__(self, ttl_minutes: int = 60, lock_ttl_s: float = 900):
        self.ttl = ttl_minutes * 60
        self.lock_ttl = lock_ttl_s
        self._items: dict[str, tuple[Session, float]] = {}
        self._locks: dict[str, tuple[str, float]] = {}

    async def get(self, session_id: str) -> Session | None:
        self._prune()
        item = self._items.get(session_id)
        if item is None:
            return None
        self._items[session_id] = (item[0], time.monotonic())
        return item[0]

    async def save(self, session: Session) -> None:
        self._items[session.id] = (session, time.monotonic())

    async def try_lock(self, session_id: str) -> str | None:
        now = time.monotonic()
        held = self._locks.get(session_id)
        if held and held[1] > now:
            return None
        token = secrets.token_hex(8)
        self._locks[session_id] = (token, now + self.lock_ttl)
        return token

    async def unlock(self, session_id: str, token: str) -> None:
        held = self._locks.get(session_id)
        if held and held[0] == token:
            del self._locks[session_id]

    async def close(self) -> None:
        return None

    def _prune(self) -> None:
        cutoff = time.monotonic() - self.ttl
        for sid in [k for k, (_, seen) in self._items.items() if seen < cutoff and k not in self._locks]:
            del self._items[sid]

    def __len__(self) -> int:
        return len(self._items)


# Delete the lock only if we still own it (another replica may hold it after our TTL ran out).
_UNLOCK = """
if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end
return 0
"""


class RedisSessions:
    """Sessions as JSON strings with a TTL; locks with SET NX PX. Keys: `sess:<id>`, `lock:<id>`."""

    def __init__(self, client, ttl_minutes: int = 60, lock_ttl_s: float = 900):
        self.r = client
        self.ttl = ttl_minutes * 60
        self.lock_ttl_ms = int(lock_ttl_s * 1000)
        self._unlock = client.register_script(_UNLOCK)

    @classmethod
    def from_url(cls, url: str, **kw) -> "RedisSessions":
        import redis.asyncio as redis

        return cls(redis.from_url(url, socket_timeout=5, health_check_interval=30), **kw)

    async def get(self, session_id: str) -> Session | None:
        raw = await self.r.getex(f"sess:{session_id}", ex=self.ttl)  # read refreshes the TTL
        return Session.from_json(raw) if raw else None

    async def save(self, session: Session) -> None:
        await self.r.set(f"sess:{session.id}", session.to_json(), ex=self.ttl)

    async def try_lock(self, session_id: str) -> str | None:
        token = secrets.token_hex(8)
        ok = await self.r.set(f"lock:{session_id}", token, nx=True, px=self.lock_ttl_ms)
        return token if ok else None

    async def unlock(self, session_id: str, token: str) -> None:
        await self._unlock(keys=[f"lock:{session_id}"], args=[token])

    async def ping(self) -> bool:
        try:
            return bool(await self.r.ping())
        except Exception:
            return False

    async def close(self) -> None:
        await self.r.aclose()
