-- Applied at startup by agent-api and by the ingest CLI. Idempotent.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS meta (
    key   text PRIMARY KEY,
    value text NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    sku               text PRIMARY KEY,
    name              text NOT NULL,
    category          text NOT NULL DEFAULT '',
    manufacturer      text NOT NULL DEFAULT '',
    summary           text NOT NULL DEFAULT '',
    specs             jsonb NOT NULL DEFAULT '{}',
    price             numeric(14, 2),
    currency          text,
    price_valid_until date,
    price_visibility  text NOT NULL DEFAULT 'internal' CHECK (price_visibility IN ('public', 'internal')),
    stock             integer CHECK (stock >= 0),
    stock_location    text,
    stock_as_of       date,
    visibility        text NOT NULL DEFAULT 'public' CHECK (visibility IN ('public', 'internal')),
    source            text NOT NULL DEFAULT '',
    updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    id         text PRIMARY KEY,
    sku        text REFERENCES products (sku) ON DELETE CASCADE,
    title      text NOT NULL DEFAULT '',
    text       text NOT NULL,
    source     text NOT NULL,
    page       integer,
    lang       text NOT NULL DEFAULT '',
    visibility text NOT NULL CHECK (visibility IN ('public', 'internal')),
    embedding  vector(384) NOT NULL,
    -- accent-folded, lowercased title + text (computed in Python; 'simple' config does not unaccent)
    search_text text NOT NULL,
    tsv        tsvector GENERATED ALWAYS AS (to_tsvector('simple', search_text)) STORED
);
CREATE INDEX IF NOT EXISTS chunks_tsv ON chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_source ON chunks (source);

-- Mock calendar. Only booking fields are stored; chat content is never stored.
CREATE TABLE IF NOT EXISTS appointments (
    id              text PRIMARY KEY,
    idempotency_key text NOT NULL UNIQUE,
    session_id      text NOT NULL,
    type            text NOT NULL,
    slot_start      timestamptz NOT NULL,
    name            text NOT NULL,
    contact         text NOT NULL,
    product_sku     text,
    status          text NOT NULL DEFAULT 'booked' CHECK (status IN ('booked', 'cancelled')),
    created_at      timestamptz NOT NULL DEFAULT now()
);
-- One booking per slot (single shared resource in the mock).
CREATE UNIQUE INDEX IF NOT EXISTS appointments_slot_booked ON appointments (slot_start) WHERE status = 'booked';

CREATE TABLE IF NOT EXISTS feedback (
    id         bigserial PRIMARY KEY,
    session_id text NOT NULL,
    rating     smallint NOT NULL CHECK (rating IN (-1, 1)),
    created_at timestamptz NOT NULL DEFAULT now()
);
