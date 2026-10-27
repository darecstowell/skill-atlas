#!/usr/bin/env bash
# Start Skill Atlas in the background and print its URL. The /skills-atlas plugin command runs this.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
log="${TMPDIR:-/tmp}/skill-atlas.log"
if command -v uvx >/dev/null 2>&1; then
  cmd=(uvx --from git+https://github.com/darecstowell/skill-atlas skill-atlas)
else
  cmd=(bash "$here/atlas")
fi
PYTHONUNBUFFERED=1 nohup "${cmd[@]}" >"$log" 2>&1 &
pid=$!
for _ in $(seq 1 120); do
  url="$(grep -o 'http://127\.0\.0\.1:[0-9]*/' "$log" | head -1 || true)"
  if [ -n "$url" ]; then
    echo "Skill Atlas runs on $url (pid $pid, log $log). Stop it with: kill $pid"
    exit 0
  fi
  kill -0 "$pid" 2>/dev/null || break
  sleep 0.5
done
echo "Skill Atlas did not start. Log: $log" >&2
tail -n 20 "$log" >&2
exit 1
