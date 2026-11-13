#!/bin/zsh
set -e
cd "${0:A:h}"
runtime_python="${HOME}/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
if [[ ! -x "$runtime_python" ]]; then runtime_python="$(command -v python3)"; fi
export PATH="/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS:$PATH"
if [[ ! -f .env ]]; then export CHIGUA_PROVIDER="${CHIGUA_PROVIDER:-codex}"; fi
open "http://127.0.0.1:8765"
exec "$runtime_python" -m chigua.server --port 8765
