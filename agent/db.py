"""Postgres connection pool shared by the catalog store, the mock calendar and feedback."""

from pathlib import Path

from pgvector.psycopg import register_vector
from psycopg import Connection
from psycopg_pool import ConnectionPool

SCHEMA = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


def _configure(conn: Connection) -> None:
    register_vector(conn)


def make_pool(url: str, min_size: int = 1, max_size: int = 8) -> ConnectionPool:
    apply_schema(url)
    pool = ConnectionPool(
        url, min_size=min_size, max_size=max_size, configure=_configure, timeout=10, open=False
    )
    pool.open(wait=True, timeout=30)
    return pool


def apply_schema(url: str) -> None:
    import psycopg

    with psycopg.connect(url, connect_timeout=10, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(424242)")  # several replicas may start at once
        try:
            conn.execute(SCHEMA.read_text())
        finally:
            conn.execute("SELECT pg_advisory_unlock(424242)")


def check_embedder(pool: ConnectionPool, name: str, write: bool) -> None:
    """The ingest CLI records the embedding model; the API refuses to start with a different one."""
    with pool.connection() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = 'embedding_model'").fetchone()
        if row is None or write:
            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('embedding_model', %s) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (name,),
            )
        elif row[0] != name:
            raise RuntimeError(
                f"catalog was embedded with {row[0]!r} but EMBEDDING_MODEL={name!r}; re-run ingest"
            )
