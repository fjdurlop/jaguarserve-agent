"""Tool-calling probe against a running vLLM (plan 2.2 / 2.4). No agent-api needed.

    uv run python -m eval.probe_tools                       # uses LLM_BASE_URL / LLM_MODEL
    uv run python -m eval.probe_tools --base-url http://localhost:8002/v1

Sends 20 single-turn prompts (es/en) with the agent's tool schemas and checks the first tool the model
picks. Prints tool-call success, time to first token and output tokens/s.
"""

import argparse
import asyncio
import json
import time

from openai import AsyncOpenAI

from agent.config import get_settings
from agent.tools import tools_for

PROBES = [
    ("Do you have a portable ultrasound?", "search_catalog"),
    ("¿Tienen ultrasonido portátil?", "search_catalog"),
    ("What are the specs of the KI-PM-500?", "get_product"),
    ("Especificaciones del NH-DF-3", "get_product"),
    ("Is the QB-EC-12 in stock?", "check_availability"),
    ("¿Hay existencias del KI-OC-5?", "check_availability"),
    ("How much is the VM-US-210?", "get_price"),
    ("¿Cuánto cuesta el KI-PO-10?", "get_price"),
    ("Price for 3 units of NH-BD-E5", "get_price"),
    ("I want to book a demo next week", "list_slots"),
    ("Quiero agendar una visita de servicio", "list_slots"),
    ("Which defibrillators do you sell?", "search_catalog"),
    ("Recomiéndame un monitor de signos vitales para consultorio", "search_catalog"),
    ("List your sterilizers", "list_products"),
    ("Compare SonoLite 210 and SonoPocket H1 battery life", "get_product"),
    ("¿Qué centrífugas tienen?", "search_catalog"),
    ("Any safety notices about electrical safety standards? Search the web.", "web_search"),
    ("Is the BreathLine T2 available?", "check_availability"),
    ("Necesito un oxímetro de mesa con impresora", "search_catalog"),
    ("What is the warranty on new devices?", "search_catalog"),
]


async def probe(client: AsyncOpenAI, model: str, tools: list[dict], prompt: str, think: bool) -> dict:
    t0 = time.monotonic()
    first = None
    name = ""
    out_chars = 0
    stream = await client.chat.completions.create(
        model=model,
        stream=True,
        tools=tools,
        tool_choice="auto",
        temperature=0.2,
        max_tokens=400,
        messages=[
            {"role": "system", "content": "You are an equipment catalog assistant. Use tools."},
            {"role": "user", "content": prompt},
        ],
        extra_body={"chat_template_kwargs": {"enable_thinking": think}},
    )
    async for chunk in stream:
        if not chunk.choices:
            continue
        d = chunk.choices[0].delta
        if (d.content or d.tool_calls) and first is None:
            first = time.monotonic() - t0
        out_chars += len(d.content or "")
        for tc in d.tool_calls or []:
            if tc.function and tc.function.name and not name:
                name = tc.function.name
            out_chars += len((tc.function.arguments or "") if tc.function else "")
    total = time.monotonic() - t0
    return {
        "tool": name,
        "ttft_s": round(first or total, 3),
        "total_s": round(total, 3),
        "approx_tok_s": round(out_chars / 4 / max(total - (first or 0), 1e-3), 1),
    }


async def main() -> None:
    s = get_settings()
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=s.llm_base_url)
    ap.add_argument("--model", default=s.llm_model)
    ap.add_argument("--think", action="store_true")
    args = ap.parse_args()
    client = AsyncOpenAI(base_url=args.base_url, api_key=s.llm_api_key or "EMPTY", timeout=120)
    tools = tools_for("public", True, s.appointment_type_list)
    ok = 0
    rows = []
    for prompt, expected in PROBES:
        r = await probe(client, args.model, tools, prompt, args.think)
        r.update(prompt=prompt, expected=expected, ok=r["tool"] == expected)
        ok += r["ok"]
        rows.append(r)
        print(json.dumps(r, ensure_ascii=False))
    ttfts = sorted(r["ttft_s"] for r in rows)
    print(
        f"\ntool-call success {ok}/{len(PROBES)} · TTFT p50 {ttfts[len(ttfts) // 2]} s · "
        f"p95 {ttfts[int(len(ttfts) * 0.95) - 1]} s · model {args.model}"
    )


if __name__ == "__main__":
    asyncio.run(main())
