#!/usr/bin/env bash
# CI runner: runs every tests/test_*.py ONE BY ONE (each is a standalone script), lists the failures,
# exits non-zero if any failed. tests/ekranli/ is never run (it touches a real screen).
# Usage: tests/ci_kos.sh   (from anywhere; the caller sets up DISPLAY / session bus)
set -u
cd "$(dirname "$0")/.." || exit 1
basarisiz=()
gecen=0
for t in tests/test_*.py; do
  echo "::group::$t"
  if timeout 600 python3 "$t"; then
    gecen=$((gecen + 1))
  else
    rc=$?
    echo "FAILED: $t (exit $rc)"
    basarisiz+=("$t")
  fi
  echo "::endgroup::"
done
echo
echo "passed suites: $gecen, failed suites: ${#basarisiz[@]}"
if [ "${#basarisiz[@]}" -gt 0 ]; then
  printf 'FAILED: %s\n' "${basarisiz[@]}"
  exit 1
fi
