"""Ingest CLI.

uv run python -m ingest data/demo_catalog                # into DATABASE_URL (STORE=pg)
uv run python -m ingest data/demo_catalog --dry-run      # parse + validate only
"""

import argparse
import json
import sys
from pathlib import Path

from agent.catalog.memory import MemoryCatalog
from agent.config import get_settings
from agent.embeddings import get_embedder
from ingest import load_catalog


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="ingest", description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    ap.add_argument("path", type=Path)
    ap.add_argument("--dry-run", action="store_true", help="parse and validate; write nothing")
    ap.add_argument("--rejects", type=Path, default=Path("ingest_rejects.jsonl"))
    args = ap.parse_args()
    s = get_settings()
    embedder = get_embedder(s.embedding_model)

    if args.dry_run or s.store == "memory":
        store = MemoryCatalog(embedder)
    else:
        from agent.catalog.pg import PgCatalog
        from agent.db import check_embedder, make_pool

        pool = make_pool(s.database_url)
        check_embedder(pool, embedder.name, write=True)
        store = PgCatalog(pool, embedder)

    report = load_catalog(args.path, store, dry_run=args.dry_run)
    print(report.summary())
    if report.rejects:
        args.rejects.write_text("\n".join(json.dumps(r) for r in report.rejects) + "\n")
        print(f"rejects written to {args.rejects}")
    if s.store == "memory" and not args.dry_run:
        print("STORE=memory: nothing persisted (the API loads CATALOG_PATH at startup)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
