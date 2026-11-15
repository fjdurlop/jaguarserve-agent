"""Prometheus metrics. Labels are low-cardinality; no message content, no session ids."""

from prometheus_client import Counter, Gauge, Histogram

TURNS = Counter("agent_turns_total", "Chat turns", ["role", "outcome"])
TOOL_CALLS = Counter("agent_tool_calls_total", "Tool calls", ["tool", "status"])
BOOKINGS = Counter("agent_bookings_total", "Booking attempts", ["status"])
REFUSALS = Counter("agent_refusals_total", "Refused turns", ["reason"])
GUARD = Counter("agent_guardrail_violations_total", "Guardrail findings", ["kind"])
TURN_SECONDS = Histogram("agent_turn_seconds", "Turn latency", buckets=(0.5, 1, 2, 4, 8, 15, 30, 60, 120))
FIRST_TOKEN = Histogram(
    "agent_llm_first_token_seconds",
    "Time to first LLM token per call",
    buckets=(0.1, 0.25, 0.5, 1, 2, 4, 8, 15),
)
# KEDA wakes vLLM from zero when sum(agent_llm_waiting_turns) > 0 (a user waits; vLLM not up yet).
LLM_WAITING = Gauge("agent_llm_waiting_turns", "Turns waiting for the LLM to become ready")
LLM_WAIT = Histogram(
    "agent_llm_wait_seconds", "Time waiting for a cold LLM", buckets=(1, 5, 15, 30, 60, 120, 240, 420, 600)
)
