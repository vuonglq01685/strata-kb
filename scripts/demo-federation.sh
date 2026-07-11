#!/usr/bin/env bash
# Demo federation Phase 3: hub bare + 2 repo con, chạy trọn vòng.
# Yêu cầu: đã `pip install -e .` và có git. Chạy từ root repo CENTER-KB.
set -euo pipefail

# Trên Windows/Git Bash, console mặc định dùng codepage cp1252 — output có
# dấu tiếng Việt hoặc "§" sẽ làm `kb` crash với UnicodeEncodeError nếu không
# ép stdout sang UTF-8. Không ảnh hưởng trên Linux/macOS (đã là UTF-8 sẵn).
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"

WORK=$(mktemp -d)
export CENTER_KB_HUB_CACHE="$WORK/cache"
export CENTER_KB_HUB_TTL=0
trap 'rm -rf "$WORK"' EXIT
echo "== Demo federation trong $WORK"

git_c() { git -C "$1" -c user.name=demo -c user.email=demo@local "${@:2}"; }

# --- 1. Dựng hub: 1 doc domain + federation/ rỗng ---
HUB="$WORK/kb-hub"
mkdir -p "$HUB/.kb/arinc-424" "$HUB/federation"
cat > "$HUB/.kb/index.yaml" <<'YAML'
docs:
  - id: arinc-424
    title: "ARINC 424"
    revision: "Supplement 22"
    tags: [arinc424, airspace]
    summary: "Navigation database spec."
YAML
cat > "$HUB/.kb/arinc-424/_manifest.yaml" <<'YAML'
id: arinc-424
title: "ARINC 424"
revision: "Supplement 22"
sections:
  - id: "5.3"
    title: "Restrictive Airspace"
    summary: "Restrictive airspace: designation, type, multiple code."
    status: reviewed
    file: ch5-airspace
YAML
printf '## 5.3 Restrictive Airspace\n\nDesignation, type, multiple code, level.\n' \
  > "$HUB/.kb/arinc-424/ch5-airspace.md"
cp "$HUB/.kb/arinc-424/ch5-airspace.md" "$HUB/.kb/arinc-424/ch5-airspace.raw.md"
touch "$HUB/federation/.gitkeep"
git_c "$HUB" init -q && git_c "$HUB" add -A && git_c "$HUB" commit -qm "hub v1"
BARE="$WORK/hub.git"
git init -q --bare "$BARE"
git_c "$HUB" remote add origin "$BARE" && git_c "$HUB" push -q origin HEAD

# --- 2. Dựng 2 repo con demo-nav-data / demo-crew-ops ---
make_repo() { # $1=path $2=doc-id $3=tag $4=summary
  mkdir -p "$1/.kb/$2"
  printf 'docs:\n  - id: %s\n    title: "%s"\n    tags: [%s]\n    summary: "%s"\n' \
    "$2" "$2" "$3" "$4" > "$1/.kb/index.yaml"
  printf 'id: %s\ntitle: "%s"\nsections:\n  - id: "1.1"\n    title: "Overview"\n    summary: "%s"\n    status: reviewed\n    file: ch1\n' \
    "$2" "$2" "$4" > "$1/.kb/$2/_manifest.yaml"
  printf '## 1.1 Overview\n\n%s\n' "$4" > "$1/.kb/$2/ch1.md"
  cp "$1/.kb/$2/ch1.md" "$1/.kb/$2/ch1.raw.md"
  git_c "$1" init -q && git_c "$1" add -A && git_c "$1" commit -qm "v1"
}
make_repo "$WORK/demo-nav-data" nav-mapping navdata "Mapping ARINC records to nav-data services."
make_repo "$WORK/demo-crew-ops" roster-sop crewops "Crew roster duty limits and rest rules."

# --- 3. Publish cả hai lên hub ---
(cd "$WORK/demo-nav-data" && kb publish --hub "$BARE" --repo-id demo-nav-data)
(cd "$WORK/demo-crew-ops" && kb publish --hub "$BARE" --repo-id demo-crew-ops)

# --- 4. Query từ repo A: thấy hub (full L2) + repo B [remote] ---
echo "== Query domain hub từ demo-nav-data:"
(cd "$WORK/demo-nav-data" && kb query "restrictive airspace" --hub "$BARE")
echo "== Query chéo sang demo-crew-ops (chỉ summary [remote]):"
(cd "$WORK/demo-nav-data" && kb query "crew roster duty rest" --hub "$BARE")

# --- 5. context new pin hub_version ---
echo "== Block kb-context cite tài liệu hub:"
BLOCK=$(cd "$WORK/demo-nav-data" && kb context new --refs "arinc-424 §5.3" --hub "$BARE")
echo "$BLOCK"

# --- 6. Amendment hub → resolve báo stale ---
# `kb publish` (bước 3) đã push trực tiếp vào $BARE qua cache riêng của nó
# (CENTER_KB_HUB_CACHE), tách biệt với working copy $HUB dựng ở bước 1 — nên
# $HUB giờ đang sau $BARE vài commit, phải đồng bộ lại trước khi amend + push.
git_c "$HUB" pull -q --ff-only origin HEAD
sed -i.bak 's/multiple code, level./multiple code, level, NEW field./' \
  "$HUB/.kb/arinc-424/ch5-airspace.md" && rm -f "$HUB/.kb/arinc-424/ch5-airspace.md.bak"
git_c "$HUB" add -A && git_c "$HUB" commit -qm "amendment" && git_c "$HUB" push -q origin HEAD
echo "== Resolve sau amendment (mong đợi stale, exit 2):"
set +e
(cd "$WORK/demo-nav-data" && echo "$BLOCK" | kb resolve - --hub "$BARE")
echo "exit=$?"
set -e

# --- 7. doctor bắt index lệch ---
(cd "$WORK/demo-nav-data" && touch note.txt && git_c "$WORK/demo-nav-data" add -A \
  && git_c "$WORK/demo-nav-data" commit -qm "chua publish")
echo "== Doctor sau khi repo có commit chưa publish (mong đợi lệch/chưa đồng bộ):"
set +e
(cd "$WORK/demo-nav-data" && kb doctor --hub "$BARE")
echo "exit=$?"
set -e
echo "== Demo xong."
