#!/usr/bin/env bash
# Demo: hub federation = single source of truth.
# Build kb-hub + 2 child repos in a temp directory, publish (direct mode),
# cross-repo search, citation pin, stale after amendment. Cleans up after itself.
set -euo pipefail

DEMO_DIR="$(mktemp -d)"
trap 'rm -rf "$DEMO_DIR"' EXIT
export CENTER_KB_HUB_CACHE="$DEMO_DIR/.hub-cache"
G() { git -C "$1" -c user.name=demo -c user.email=demo@local -c core.excludesFile= "${@:2}"; }

echo "== 1. Build kb-hub =="
HUB="$DEMO_DIR/kb-hub"
mkdir -p "$HUB/.kb" "$HUB/federation"
printf 'docs: []\n' > "$HUB/.kb/index.yaml"
touch "$HUB/federation/.gitkeep"
git init -q "$HUB"; G "$HUB" add -A; G "$HUB" commit -qm "hub v0"

make_repo() { # $1=name $2=doc $3=sec $4=keyword
  local ROOT="$DEMO_DIR/$1" DOC="$DEMO_DIR/$1/.kb/$2"
  mkdir -p "$DOC"
  printf '## %s Title\n\nCondensed %s content.\n' "$3" "$4" > "$DOC/ch1.md"
  printf '## %s Title\n\nVerbatim %s content.\n' "$3" "$4" > "$DOC/ch1.raw.md"
  cat > "$DOC/_manifest.yaml" <<EOF
id: $2
title: $2
sections:
  - id: '$3'
    title: Title
    summary: $4 summary.
    status: summarized
    file: ch1
EOF
  cat > "$DEMO_DIR/$1/.kb/index.yaml" <<EOF
docs:
  - id: $2
    title: $2
    tags: [$1]
    summary: $4 doc.
EOF
  printf 'hub: %s\nrepo_id: %s\n' "$HUB" "$1" > "$DEMO_DIR/$1/.kb/config.yaml"
  git init -q "$ROOT"; G "$ROOT" add -A; G "$ROOT" commit -qm "v1"
}

echo "== 2. Build the 2 child repos =="
make_repo repo-alpha alpha-spec 1.1 "alpha widget"
make_repo repo-beta  beta-spec  2.1 "beta gadget"

echo "== 3. Publish both (direct mode — hub local path) =="
kb publish --kb-dir "$DEMO_DIR/repo-alpha/.kb"
kb publish --kb-dir "$DEMO_DIR/repo-beta/.kb"

echo "== 4. Aggregate index on the hub =="
cat "$HUB/federation/index.yaml"

echo "== 5. Cross-repo search from repo-alpha (reads federation only) =="
kb query "beta gadget" --kb-dir "$DEMO_DIR/repo-alpha/.kb"

echo "== 6. L3 verbatim via the hub =="
kb get beta-spec 2.1 --level l3 --kb-dir "$DEMO_DIR/repo-alpha/.kb"

echo "== 7. Pin citation at hub HEAD =="
kb context new --refs "beta-spec §2.1" --kb-dir "$DEMO_DIR/repo-alpha/.kb" | tee "$DEMO_DIR/ticket.md"

echo "== 8. Amendment in repo-beta + republish → citation stale =="
sed -i.bak 's/Condensed beta/Condensed AMENDED beta/' "$DEMO_DIR/repo-beta/.kb/beta-spec/ch1.md"
G "$DEMO_DIR/repo-beta" add -A; G "$DEMO_DIR/repo-beta" commit -qm "amendment"
kb publish --kb-dir "$DEMO_DIR/repo-beta/.kb"
kb resolve "$DEMO_DIR/ticket.md" --kb-dir "$DEMO_DIR/repo-alpha/.kb" || true

echo "== 9. Multi-tier: root hub + mid hub =="
ROOT_HUB="$DEMO_DIR/kb-root-hub"
mkdir -p "$ROOT_HUB/.kb" "$ROOT_HUB/federation"
printf 'docs: []\n' > "$ROOT_HUB/.kb/index.yaml"
printf 'kind: hub\nrepo_id: root-hub\n' > "$ROOT_HUB/.kb/config.yaml"
touch "$ROOT_HUB/federation/.gitkeep"
git init -q "$ROOT_HUB"; G "$ROOT_HUB" add -A; G "$ROOT_HUB" commit -qm "root hub v0"

# Biến hub cũ thành hub trung gian: khai kind + upstream
printf 'kind: hub\nrepo_id: mid\nhub: %s\n' "$ROOT_HUB" > "$HUB/.kb/config.yaml"
git init -q "$HUB" 2>/dev/null || true
G "$HUB" add -A; G "$HUB" commit -qm "mid hub config" || true

echo "== 10. Mid hub publishes its federation upstream =="
kb publish --kb-dir "$HUB/.kb"
echo "-- aggregate index on the ROOT hub (nested ids mid/...):"
cat "$ROOT_HUB/federation/index.yaml"

echo "== 11. Query at the root sees every tier =="
ROOT_QUERY_OUT="$(kb query "beta gadget" --hub "$ROOT_HUB" --kb-dir "$DEMO_DIR/repo-alpha/.kb")"
echo "$ROOT_QUERY_OUT"
if ! echo "$ROOT_QUERY_OUT" | grep -q "mid/repo-beta"; then
  echo "-- ERROR: root query did not show nested id" && exit 1
fi

echo "== 12. Cycle demo: root hub pointed back at mid → publish refuses =="
printf 'kind: hub\nrepo_id: root-hub\nhub: %s\n' "$HUB" > "$ROOT_HUB/.kb/config.yaml"
G "$ROOT_HUB" add -A; G "$ROOT_HUB" commit -qm "misconfigure: point back at mid"
# kb publish exits 1 on a refused cycle (PublishError) — capture rc explicitly
# instead of piping straight into `grep -q`: under `set -o pipefail` the
# pipeline's exit status is kb publish's nonzero code regardless of grep's
# own (successful) match, which would always trip the `else` branch below.
set +e
CYCLE_OUT="$(kb publish --kb-dir "$ROOT_HUB/.kb" 2>&1)"
CYCLE_RC=$?
set -e
if [ "$CYCLE_RC" -ne 0 ] && echo "$CYCLE_OUT" | grep -q "federation cycle detected"; then
  echo "-- cycle correctly refused"
else
  echo "-- ERROR: cycle was NOT refused" && exit 1
fi

echo "== Demo complete — hub federation is the only read source =="
