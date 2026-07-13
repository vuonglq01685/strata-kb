#!/usr/bin/env bash
# Demo: hub federation = single source of truth.
# Dựng kb-hub + 2 repo con trong thư mục tạm, publish (direct mode),
# search cross-repo, citation pin, stale sau amendment. Tự dọn dẹp.
set -euo pipefail

DEMO_DIR="$(mktemp -d)"
trap 'rm -rf "$DEMO_DIR"' EXIT
export CENTER_KB_HUB_CACHE="$DEMO_DIR/.hub-cache"
G() { git -C "$1" -c user.name=demo -c user.email=demo@local -c core.excludesFile= "${@:2}"; }

echo "== 1. Dựng kb-hub =="
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

echo "== 2. Dựng 2 repo con =="
make_repo repo-alpha alpha-spec 1.1 "alpha widget"
make_repo repo-beta  beta-spec  2.1 "beta gadget"

echo "== 3. Publish cả hai (direct mode — hub local path) =="
kb publish --kb-dir "$DEMO_DIR/repo-alpha/.kb"
kb publish --kb-dir "$DEMO_DIR/repo-beta/.kb"

echo "== 4. Index tổng trên hub =="
cat "$HUB/federation/index.yaml"

echo "== 5. Search cross-repo từ repo-alpha (chỉ đọc federation) =="
kb query "beta gadget" --kb-dir "$DEMO_DIR/repo-alpha/.kb"

echo "== 6. L3 verbatim qua hub =="
kb get beta-spec 2.1 --level l3 --kb-dir "$DEMO_DIR/repo-alpha/.kb"

echo "== 7. Pin citation tại HEAD hub =="
kb context new --refs "beta-spec §2.1" --kb-dir "$DEMO_DIR/repo-alpha/.kb" | tee "$DEMO_DIR/ticket.md"

echo "== 8. Amendment ở repo-beta + republish → citation stale =="
sed -i.bak 's/Condensed beta/Condensed AMENDED beta/' "$DEMO_DIR/repo-beta/.kb/beta-spec/ch1.md"
G "$DEMO_DIR/repo-beta" add -A; G "$DEMO_DIR/repo-beta" commit -qm "amendment"
kb publish --kb-dir "$DEMO_DIR/repo-beta/.kb"
kb resolve "$DEMO_DIR/ticket.md" --kb-dir "$DEMO_DIR/repo-alpha/.kb" || true

echo "== Demo hoàn tất — hub federation là nguồn đọc duy nhất =="
