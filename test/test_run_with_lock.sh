#!/bin/bash
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
JOB="onboarding_lock_test_$$"
LOCK="/tmp/checksheets_locks/$JOB.lock"
sleep 30 &
OWNER=$!
cleanup() {
  kill "$OWNER" 2>/dev/null || true
  wait "$OWNER" 2>/dev/null || true
  rm -f "$LOCK"
  find "$ROOT/logs" -name "${JOB}_*.log" -delete
}
trap cleanup EXIT
mkdir -p /tmp/checksheets_locks
echo "$OWNER" > "$LOCK"
set +e
CHECKSHEETS_REQUIRE_JOB_RUN=1 "$ROOT/run_with_lock.sh" "$JOB"
RESULT=$?
set -e
test "$RESULT" -eq 75
test "$(cat "$LOCK")" = "$OWNER"
"$ROOT/run_with_lock.sh" "$JOB"
test "$(cat "$LOCK")" = "$OWNER"
echo 'PASS busy job returns deferred for onboarding and preserves the owner lock'
