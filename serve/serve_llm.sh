#!/usr/bin/env bash
# Start vLLM (OpenAI-compatible API, tool calling, prefix caching, /metrics) for one model profile.
#
#   serve/serve_llm.sh                 # profile A (default)
#   PROFILE=model_b serve/serve_llm.sh # profile B (needs a 24 GB GPU)
#
# Long-running: run it in its own terminal. Machine-specific env vars (CUDA paths, WSL flags) go in
# serve/local.env, which is gitignored and sourced if present.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILE="${PROFILE:-model_a}"
# shellcheck disable=SC1090
source "$HERE/profiles/$PROFILE.env"
[[ -f "$HERE/local.env" ]] && source "$HERE/local.env"
: "${MODEL:?profile must set MODEL}"

exec "${VLLM_BIN:-vllm}" serve "$MODEL" \
  ${QUANT_FLAGS} \
  --served-model-name "${SERVED_NAME:-$MODEL}" \
  --max-model-len "${MAX_MODEL_LEN}" \
  --gpu-memory-utilization "${GPU_MEM_UTIL}" \
  --enable-auto-tool-choice --tool-call-parser "${TOOL_PARSER:-hermes}" \
  --enable-prefix-caching \
  --host "${HOST:-0.0.0.0}" --port "${PORT:-8002}" \
  ${EXTRA_FLAGS:-}
