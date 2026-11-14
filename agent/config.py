"""Settings from environment variables. Every variable is listed in `.env.example`."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    # LLM (OpenAI-compatible, normally vLLM)
    llm_base_url: str = "http://localhost:8002/v1"
    llm_model: str = "Qwen/Qwen3-14B-AWQ"
    llm_api_key: str = "EMPTY"
    llm_timeout: float = 60.0
    llm_ready_timeout: float = 420.0  # cold start from zero can take minutes
    llm_enable_thinking: bool = False
    llm_temperature: float = 0.3
    llm_max_tokens: int = 1024
    llm_fallback_base_url: str = ""
    llm_fallback_model: str = ""
    llm_fallback_api_key: str = ""

    # Web search
    search_provider: str = "fake"  # fake | searxng | brave | off
    search_url: str = ""  # searxng base URL
    search_api_key: str = ""  # brave
    search_allow_list: str = ""  # comma-separated domains; empty disables web tools

    # Catalog store + embeddings
    store: str = "memory"  # memory | pg
    database_url: str = ""
    embedding_model: str = "hash"  # "hash" (offline, tests) or a fastembed model name
    catalog_path: str = "data/demo_catalog"  # loaded at startup when store=memory

    # Booking
    calendar_provider: str = "mock"
    appointment_types: str = "demo,service_visit,sales_call"
    business_hours: str = "mon-fri 09:00-17:00"
    slot_minutes: int = 60
    booking_lead_hours: int = 2
    timezone: str = "UTC"
    privacy_notice_url: str = ""

    # Roles
    internal_tokens: str = ""  # comma-separated bearer tokens for the internal role

    # Agent loop + logging
    agent_max_steps: int = 6
    agent_max_web_calls: int = 3
    tool_timeout: float = 10.0
    stream_answer: str = "checked"  # checked (guardrails before tokens) | live
    log_chat_content: bool = False

    # API
    handoff_webhook_url: str = ""
    cors_origins: str = ""
    session_ttl_minutes: int = 60
    rate_chat_per_min_ip: int = 30
    rate_chat_per_min_session: int = 15
    rate_book_per_hour_session: int = 3

    test_database_url: str = Field(default="", description="Only used by the pg test suite")

    @property
    def allow_list(self) -> list[str]:
        return [d.lower().lstrip(".") for d in _split(self.search_allow_list)]

    @property
    def appointment_type_list(self) -> list[str]:
        return _split(self.appointment_types)

    @property
    def internal_token_list(self) -> list[str]:
        return _split(self.internal_tokens)


def _split(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
