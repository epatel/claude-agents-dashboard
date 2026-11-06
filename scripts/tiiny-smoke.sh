#!/usr/bin/env bash
# Smoke-test a Tiiny device through Claude Code's Anthropic route.
#
# Runs the acceptance tests from TIINY_HARNESS_INTEGRATION.md §6 against
# http://anthropic.api.tiiny with the plain `claude` CLI, before any dashboard
# code exists:
#   1. raw endpoint  — curl /v1/messages, checks HTTP status (401/404/502/...)
#   2. text          — `claude -p "Reply with the word OK"`
#   3. tool use      — agent creates hello.txt containing "hi" and reads it back;
#                      PASS only if the file really exists on disk
#
# API key: $TIINY_API_KEY, else macOS Keychain (service "tiiny-api-key"),
# else a hidden prompt. The key is never printed.
#   Store it once in the Keychain:
#     security add-generic-password -s tiiny-api-key -a "$USER" -w
#
# Usage: scripts/tiiny-smoke.sh [model-id]     (default: "default")
# Env:   TIINY_BASE_URL (default http://anthropic.api.tiiny)
#        TIINY_TIMEOUT  seconds per claude run (default 300)

set -uo pipefail

MODEL="${1:-default}"
BASE_URL="${TIINY_BASE_URL:-http://anthropic.api.tiiny}"
TIMEOUT="${TIINY_TIMEOUT:-300}"

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
bold()  { printf '\033[1m%s\033[0m\n' "$*"; }

command -v claude >/dev/null || { red "claude CLI not found on PATH"; exit 1; }
command -v curl   >/dev/null || { red "curl not found"; exit 1; }

# --- API key -----------------------------------------------------------------
KEY="${TIINY_API_KEY:-}"
if [ -z "$KEY" ] && command -v security >/dev/null; then
  KEY="$(security find-generic-password -s tiiny-api-key -w 2>/dev/null || true)"
  [ -n "$KEY" ] && echo "Using API key from Keychain (tiiny-api-key)"
fi
if [ -z "$KEY" ]; then
  read -r -s -p "Tiiny API key (TiinyOS → Settings → API Key): " KEY; echo
fi
# Strip quotes and whitespace (common copy-paste damage)
KEY="$(printf '%s' "$KEY" | tr -d '[:space:]"'"'")"
[ -n "$KEY" ] || { red "No API key given"; exit 1; }

TMP_ROOT="${TMPDIR:-/tmp}"
WORK="$(mktemp -d "${TMP_ROOT%/}/tiiny-smoke.XXXXXX")"
echo "Base URL: $BASE_URL   Model: $MODEL   Work dir: $WORK"
echo

PASS=0; FAIL=0
pass() { green "  PASS: $*"; PASS=$((PASS+1)); }
fail() { red   "  FAIL: $*"; FAIL=$((FAIL+1)); }

explain_status() {
  case "$1" in
    200) echo "OK" ;;
    401) echo "401 — API key missing or wrong (re-copy it from TiinyOS)" ;;
    404) echo "404 — wrong model ID, or no model loaded when using 'default'" ;;
    502) echo "502 — device reachable but services still starting; retry in a few minutes" ;;
    000) echo "no connection — TiinyOS not running, or this machine is not the TiinyOS host" ;;
    *)   echo "HTTP $1" ;;
  esac
}

# --- 1. Raw endpoint -----------------------------------------------------------
bold "1. Raw endpoint (POST $BASE_URL/v1/messages)"
BODY=$(printf '{"model":"%s","max_tokens":16,"messages":[{"role":"user","content":"Reply with the word OK"}]}' "$MODEL")
STATUS=$(curl -s -m 180 -o "$WORK/raw.json" -w '%{http_code}' \
  -X POST "$BASE_URL/v1/messages" \
  -H "Authorization: Bearer $KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d "$BODY")
echo "  $(explain_status "$STATUS")"
if [ "$STATUS" = "200" ]; then
  pass "endpoint answers"
  echo "  response: $(head -c 400 "$WORK/raw.json")"
else
  fail "endpoint"
  [ -s "$WORK/raw.json" ] && echo "  body: $(head -c 400 "$WORK/raw.json")"
  echo; red "Stopping: fix the endpoint first."; exit 1
fi
echo

# --- claude CLI runner ---------------------------------------------------------
# Same shape as the dashboard's planned Tiiny profile: every tier → one model,
# no user settings (keeps global hooks such as RTK out), long API timeout.
run_claude() {
  local log="$1"; shift
  ( cd "$WORK" && \
    ANTHROPIC_BASE_URL="$BASE_URL" \
    ANTHROPIC_AUTH_TOKEN="$KEY" \
    ANTHROPIC_API_KEY="" \
    ANTHROPIC_MODEL="$MODEL" \
    ANTHROPIC_DEFAULT_OPUS_MODEL="$MODEL" \
    ANTHROPIC_DEFAULT_SONNET_MODEL="$MODEL" \
    ANTHROPIC_DEFAULT_HAIKU_MODEL="$MODEL" \
    ANTHROPIC_SMALL_FAST_MODEL="$MODEL" \
    API_TIMEOUT_MS=600000 \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
    perl -e 'alarm shift; exec @ARGV' "$TIMEOUT" \
      claude -p "$@" --model "$MODEL" --setting-sources local \
             --permission-mode acceptEdits ) >"$log" 2>&1
}

check_log_errors() {
  local log="$1"
  grep -qi "signature" "$log" && red "  note: 'signature' error seen — unsigned thinking blocks (disable thinking, as for Ollama)"
  grep -qiE "401|unauthori" "$log" && red "  note: auth error in CLI output"
  grep -qiE "404|not.found" "$log" && red "  note: model not found in CLI output"
}

# --- 2. Text -----------------------------------------------------------------
bold "2. Text via claude CLI"
run_claude "$WORK/text.log" "Reply with the word OK"
RC=$?
echo "  output: $(tail -c 300 "$WORK/text.log" | tr '\n' ' ')"
if [ $RC -eq 0 ] && grep -qi "ok" "$WORK/text.log"; then pass "text reply"
else fail "text reply (exit $RC; 142 = timeout)"; check_log_errors "$WORK/text.log"; fi
echo

# --- 3. Tool use -------------------------------------------------------------
bold "3. Tool use via claude CLI"
run_claude "$WORK/tool.log" \
  "Create a file named hello.txt in the current directory containing exactly: hi
Then read the file back and tell me its contents. Use your tools; do not just print commands."
RC=$?
echo "  output: $(tail -c 300 "$WORK/tool.log" | tr '\n' ' ')"
if [ -f "$WORK/hello.txt" ] && [ "$(tr -d '[:space:]' < "$WORK/hello.txt")" = "hi" ]; then
  pass "hello.txt exists on disk with 'hi'"
else
  fail "hello.txt missing or wrong (exit $RC) — model may lack 'Tool Use' support"
  grep -q '"name"' "$WORK/tool.log" && red "  note: output contains tool-call JSON as text — tool use is NOT working"
  check_log_errors "$WORK/tool.log"
fi
echo

# --- Summary -----------------------------------------------------------------
bold "Result: $PASS passed, $FAIL failed"
echo "Logs kept in $WORK (raw.json, text.log, tool.log)"
[ $FAIL -eq 0 ]
