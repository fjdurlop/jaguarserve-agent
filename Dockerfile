# agent-api + ingest CLI (CPU only). The LLM runs in a separate vLLM container / GPU node.
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    FASTEMBED_CACHE_PATH=/cache/fastembed
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project --extra embed --extra docs
COPY agent ./agent
COPY api ./api
COPY ingest ./ingest
COPY eval ./eval
COPY db ./db
COPY web ./web
COPY data/demo_catalog ./data/demo_catalog
RUN uv sync --frozen --no-dev --extra embed --extra docs \
 && useradd --uid 10001 --create-home app && mkdir -p /cache && chown app /cache
USER 10001
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8080
CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8080", "--timeout-graceful-shutdown", "120"]
