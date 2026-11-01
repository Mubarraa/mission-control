#!/usr/bin/env bash
# Narrated end-to-end journey through `mc`. Needs: make up && make migrate && make seed, and `make run` in
# another terminal. Uses a throwaway session directory so it never touches your own `mc` login.
set -euo pipefail

export MC_API_URL="${MC_API_URL:-http://localhost:8000}"
export MC_PASSWORD="mission-control-demo"
export MC_CONFIG_DIR="$(mktemp -d)"
trap 'rm -rf "$MC_CONFIG_DIR"' EXIT

MC="uv run --quiet mc"
BOLD=$'\e[1m'; DIM=$'\e[2m'; RESET=$'\e[0m'

say()  { printf '\n%s== %s%s\n' "$BOLD" "$1" "$RESET"; }
run()  { printf '%s$ mc %s%s\n' "$DIM" "$*" "$RESET"; $MC "$@" || true; }
as()   { $MC login --org "${2:-artemis-labs}" --email "$1" >/dev/null; printf '%s(now acting as %s)%s\n' "$DIM" "$1" "$RESET"; }
json() { $MC "$@" --json; }
field(){ python3 -c "import json,sys; print(eval('json.load(sys.stdin)'+sys.argv[1]))" "$1"; }

curl -fsS "$MC_API_URL/healthz" >/dev/null || { echo "API not reachable at $MC_API_URL - run 'make run' first."; exit 1; }

say "1. Priya (Mission Lead) logs in and checks her inbox"
run login --org artemis-labs --email priya@artemis.io
run inbox

say "2. She plans a new mission with four crew slots"
CODE=$(json mission create "Shackleton Rim Traverse" --start 2027-03-02 --end 2027-03-20 | field '["code"]')
echo "Created $CODE"
run mission slot add "$CODE" --role Commander --skill piloting:4
run mission slot add "$CODE" --role Geologist --count 2 --skill geology:3 >/dev/null
run mission slot add "$CODE" --role "EVA Specialist" --skill eva:3:cert >/dev/null
run mission slot add "$CODE" --role "Flight Surgeon" --skill medicine:2

say "3. The matcher proposes a crew for the whole mission - and explains the gap"
run match "$CODE"
run match "$CODE" --explain Geologist

say "4. The closest miss is Dev's unverified Geology claim; Priya verifies it and the gap closes"
run crew verify "Dev Patel" geology
run match "$CODE"

say "5. Priya offers the suggested crew their positions"
run match "$CODE" --apply

say "6. Each offered crew member accepts from their own inbox"
for who in alice bob carol dev eve farah gabe hana ivan jo; do
  $MC login --org artemis-labs --email "$who@artemis.io" >/dev/null
  ID=$(json inbox | python3 -c "import json,sys; o=[x for x in json.load(sys.stdin)['offers'] if x['mission_code']=='$CODE']; print(o[0]['assignment_id'] if o else '')")
  if [ -n "$ID" ]; then printf '%s(now acting as %s@artemis.io)%s\n' "$DIM" "$who" "$RESET"; run assignment accept "${ID:0:8}"; fi
done

say "7. Priya submits - and cannot approve her own mission"
as priya@artemis.io
run mission submit "$CODE"
run mission approve "$CODE"

say "8. Amara (Director) sees it in her inbox and approves"
as amara@artemis.io
run inbox
run mission approve "$CODE"
run mission show "$CODE"

say "9. Tenant isolation: Orion's Director cannot see Artemis missions"
as oskar@orion.space orion-dynamics
run mission show "$CODE"

say "Done. Explore further with: mc --help"
