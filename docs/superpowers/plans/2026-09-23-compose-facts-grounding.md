# Compose facts grounding — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `<repo>-code` carries each compose service's named volumes, healthcheck command and device reservations; the SA copies them onto three new `## Technical grounding` lines that `kb ticket check` verifies; `kb ticket lint` warns when an AC is a shell command; the SA/BA wrappers and rubric stop the "DECIDED value becomes an AC" path.

**Architecture:** Three deterministic fields on `ServiceRecord` rendered into the existing L2 property table and L3 YAML block (`services.py`). One new check in `ticketcheck.py` reading those L2 rows the way `_check_tables_routes_commands` reads `Column`/`Method`/`Command`. One new warning check in `ticketlint.py` beside `_check_ac_weasel`. Template and wrapper text edits with needle tests. Spec: `docs/superpowers/specs/2026-09-23-compose-facts-grounding-design.md`.

**Tech Stack:** Python 3.11+, PyYAML, pytest via `uv run pytest`. Branch `feat/compose-facts-grounding` (spec commit `5b3eb9a`).

## Global Constraints

- **CLAUDE.md gates.** Before editing any existing function run `node .gitnexus/run.cjs impact "<symbol>" --direction upstream --repo .` and report callers; before every commit run `node .gitnexus/run.cjs detect-changes --scope all --repo .`. Index stale (`last indexed: e4eb9ae`) → run `node .gitnexus/run.cjs analyze --index-only` from the project root first. `strata-kb` MCP is down this session; the CLI fallback above is the required path. Never grep instead of impact.
- No new dependency. No CLI/MCP imports in `ticketcheck.py` or `ticketlint.py`. `mdutils.py` untouched.
- Extractor output is deterministic: every new list is `sorted()`, every new string is fixed-width truncated. Same tree, same bytes.
- Compose only: Dockerfile / k8s / sln / workspace records leave the three new fields empty.
- `healthcheck` truncation constant `HEALTHCHECK_MAX = 200`; overflow renders the first 200 characters followed by `…`.
- `kb ticket check`: new mismatches are **errors**; a missing `Volumes:`/`Healthchecks:`/`Devices:` line is a **warning**; a `-code` document whose svc L2 has no `Volumes` row makes the three checks **skip with a note**. `--heading "## Services & order"` (mission mode) is untouched.
- `kb ticket lint`: the shell check is a **warning**, suppressed on a line carrying an owned `OPEN(<owner>)` (use `acquality.owned_open_markers`), never an error. `MAX_AC` and every existing rule untouched.
- Wrapper sync: `claude-skill-sa-ticket-ground.md`, `copilot-sa-ticket-ground.prompt.md`, `cursor-sa-ticket-ground.md` must be byte-identical after their 4-line frontmatter (`tests/test_sa_ticket_ground.py::test_sa_full_wrappers_are_byte_identical_after_frontmatter`). Edit the claude skill, then **derive** the other two with the snippet in Task 6. For `ba-ticket-author`, edit claude and copilot with the same sentences, derive cursor from copilot (they differ only on frontmatter line 2).
- `docs/ac-quality.md`'s new row must use backticks, never double quotes, in the Banned column — `test_every_quoted_doc_phrase_is_in_the_detector` treats every `"…"` there as a weasel phrase.
- Commit format `<type>: <description>`; end every commit message with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- After every task: `uv run pytest tests/test_codeingest_extractors.py tests/test_ticketcheck.py tests/test_cli_ticket_check.py tests/test_ticketlint.py tests/test_templates.py tests/test_sa_ticket_ground.py tests/test_init.py -q` green. Before the last commit: full `uv run pytest -q` green.

---

## File structure

| File | Change |
|---|---|
| `src/strata_kb/codeingest/extractors/services.py` | `ServiceRecord` +3 fields; `_named_volumes`, `_healthcheck_line`, `_devices` helpers; compose reader fills them; `_render_section` adds 3 L2 rows + 3 YAML keys |
| `tests/fixtures_coderepo.py` | fixture compose gains a healthcheck + device on `airspace-service`, a named + a bind volume on `postgres` |
| `tests/test_codeingest_extractors.py` | new `TestComposeFacts` class |
| `src/strata_kb/ticketcheck.py` | `_check_compose_facts`; `_id_lines` strips code spans on the `Healthchecks` field; wired into `check()` |
| `tests/test_ticketcheck.py` | `DEFAULTS` +3 keys (appended after `Open decisions` so no existing `(line N)` assertion moves); new tests |
| `src/strata_kb/ticketlint.py` | `SHELL_COMMANDS`, `_SHELL_OPERATOR_RE`, `_check_ac_shell`; one call in `lint()` |
| `tests/test_ticketlint.py` | 4 new tests |
| `src/strata_kb/templates/init/ticket-template.md` | 3 grounding lines; DoR last item |
| `src/strata_kb/templates/init/ac-quality.md` | one table row |
| `src/strata_kb/templates/init/claude-skill-sa-ticket-ground.md` + copilot + cursor | Load step, Fill bullets, hard rule |
| `src/strata_kb/templates/init/claude-skill-ba-ticket-author.md` + copilot + cursor | Draft sentence; maturity-review rule |
| `src/strata_kb/templates/init/review-rubric.md` | one Dev-axis item |
| `src/strata_kb/templates/init/QUICKSTART-ba.md`, `QUICKSTART-dev.md` | one paragraph each |
| `tests/test_templates.py`, `tests/test_sa_ticket_ground.py` | needle tests |
| `CHANGELOG.md`, `pyproject.toml` | `## 1.3.0 — <date>` entry; `version = "1.3.0"` |

---

### Task 1: Extractor — `volumes`, `healthcheck`, `devices` on `ServiceRecord`

**Files:**
- Modify: `src/strata_kb/codeingest/extractors/services.py:71-82` (dataclass), `:200-300` (compose reader), `:921-990` (`_render_section`)
- Modify: `tests/fixtures_coderepo.py:34-46`
- Test: `tests/test_codeingest_extractors.py` (append a class at the end)

**Interfaces:**
- Produces: `ServiceRecord.volumes: list[str]`, `ServiceRecord.healthcheck: str`, `ServiceRecord.devices: list[str]`; L2 rows `| Volumes | … |`, `| Healthcheck | … |`, `| Devices | … |` (values `none` when empty, `disabled` for a disabled healthcheck); L3 YAML keys `volumes`, `healthcheck`, `devices` in that order after `env_keys`. `HEALTHCHECK_MAX = 200`. Task 2 reads the L2 rows by header name `Property`/`Value`.

- [ ] **Step 1: Impact analysis**

Run:
```bash
node .gitnexus/run.cjs analyze --index-only
node .gitnexus/run.cjs impact "_render_section" --direction upstream --repo .
node .gitnexus/run.cjs impact "_read_compose" --direction upstream --repo .
```
Report callers in the commit body if risk is HIGH/CRITICAL. Expected: both called only from `ServicesExtractor.extract` / `_read_compose` inside `services.py`.

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_codeingest_extractors.py`:

```python
class TestComposeFacts:
    """Spec 2026-09-23-compose-facts-grounding §4: volumes / healthcheck /
    devices read from compose only, deterministic, rendered in L2 and L3."""

    COMPOSE = (
        "services:\n"
        "  postgres:\n"
        "    image: postgres:16\n"
        "    volumes:\n"
        "      - pgdata:/var/lib/postgresql/data\n"
        "      - ./init:/docker-entrypoint-initdb.d\n"
        "      - /host/abs:/abs\n"
        "      - ~/home:/home\n"
        "      - ${DATA_DIR}:/data\n"
        "      - type: volume\n"
        "        source: pgwal\n"
        "        target: /wal\n"
        "    healthcheck:\n"
        "      test: [\"CMD\", \"pg_isready\", \"-U\", \"app\"]\n"
        "  nginx:\n"
        "    image: nginx:1.27-alpine\n"
        "    healthcheck:\n"
        "      test: [\"CMD-SHELL\", \"wget -qO- http://localhost/nginx-health || exit 1\"]\n"
        "  redis:\n"
        "    image: redis:7\n"
        "    healthcheck:\n"
        "      test: redis-cli ping\n"
        "  web:\n"
        "    image: web:1\n"
        "    healthcheck:\n"
        "      disable: true\n"
        "  transcoder:\n"
        "    image: ffmpeg:1\n"
        "    deploy:\n"
        "      resources:\n"
        "        reservations:\n"
        "          devices:\n"
        "            - driver: nvidia\n"
        "              capabilities: [video, gpu]\n"
        "            - capabilities: [tpu]\n"
        "  minio:\n"
        "    image: minio/minio:latest\n"
    )

    def _sections(self, tmp_path):
        root = tmp_path / "compose-facts"
        root.mkdir()
        (root / "docker-compose.yml").write_text(self.COMPOSE, encoding="utf-8")
        return _by_id(svc_ext.ServicesExtractor().extract(root, _opts(root)))

    def test_named_volumes_only_sorted(self, tmp_path):
        s = self._sections(tmp_path)["svc.postgres"]
        assert "| Volumes | pgdata, pgwal |" in s.l2_md
        assert "volumes:\n- pgdata\n- pgwal\n" in s.l3_md
        for dropped in ("./init", "/host/abs", "~/home", "DATA_DIR"):
            assert dropped not in s.l3_md

    def test_healthcheck_forms(self, tmp_path):
        secs = self._sections(tmp_path)
        assert "| Healthcheck | pg_isready -U app |" in secs["svc.postgres"].l2_md
        assert "healthcheck: pg_isready -U app\n" in secs["svc.postgres"].l3_md
        assert "| Healthcheck | wget -qO- http://localhost/nginx-health \\|\\| exit 1 |" in secs["svc.nginx"].l2_md
        assert "| Healthcheck | redis-cli ping |" in secs["svc.redis"].l2_md
        assert "| Healthcheck | disabled |" in secs["svc.web"].l2_md
        assert "healthcheck: disabled\n" in secs["svc.web"].l3_md
        assert "| Healthcheck | none |" in secs["svc.minio"].l2_md
        assert "healthcheck: none\n" in secs["svc.minio"].l3_md

    def test_healthcheck_is_truncated_at_200(self, tmp_path):
        root = tmp_path / "compose-long-hc"
        root.mkdir()
        long_cmd = "node -e " + "x" * 300
        (root / "docker-compose.yml").write_text(
            "services:\n  api:\n    image: api:1\n    healthcheck:\n"
            f"      test: {long_cmd}\n",
            encoding="utf-8",
        )
        s = _by_id(svc_ext.ServicesExtractor().extract(root, _opts(root)))["svc.api"]
        value = s.l2_md.split("| Healthcheck | ", 1)[1].split(" |", 1)[0]
        assert value == long_cmd[:200] + "…"

    def test_devices_render_driver_and_capabilities(self, tmp_path):
        secs = self._sections(tmp_path)
        assert "| Devices | nvidia:gpu,video, unknown:tpu |" in secs["svc.transcoder"].l2_md
        assert "devices:\n- nvidia:gpu,video\n- unknown:tpu\n" in secs["svc.transcoder"].l3_md
        assert "| Devices | none |" in secs["svc.minio"].l2_md
        assert "devices: []\n" in secs["svc.minio"].l3_md

    def test_yaml_key_order_after_env_keys(self, tmp_path):
        s = self._sections(tmp_path)["svc.postgres"]
        yaml_text = s.l3_md.split("```yaml\n", 1)[1].split("```", 1)[0]
        keys = [line.split(":", 1)[0] for line in yaml_text.splitlines() if line and not line.startswith(("-", " "))]
        assert keys[:8] == ["name", "image", "ports", "depends_on", "env_keys", "volumes", "healthcheck", "devices"]

    def test_dockerfile_fallback_leaves_facts_empty(self, tmp_path):
        root = tmp_path / "dockerfile-only"
        root.mkdir()
        (root / "Dockerfile").write_text("FROM python:3.12-slim\nEXPOSE 8080\n", encoding="utf-8")
        result = svc_ext.ServicesExtractor().extract(root, _opts(root))
        s = next(iter(_by_id(result).values()))
        assert "| Volumes | none |" in s.l2_md
        assert "| Healthcheck | none |" in s.l2_md
        assert "| Devices | none |" in s.l2_md

    def test_two_runs_are_byte_identical(self, tmp_path):
        a = self._sections(tmp_path)["svc.transcoder"]
        root = tmp_path / "compose-facts"
        b = _by_id(svc_ext.ServicesExtractor().extract(root, _opts(root)))["svc.transcoder"]
        assert (a.l2_md, a.l3_md) == (b.l2_md, b.l3_md)
```

Also update the fixture compose in `tests/fixtures_coderepo.py` so Task 2 has real values to ground on. Replace lines 34–46 with:

```python
    (root / "docker-compose.yml").write_text(
        "services:\n"
        "  airspace-service:\n"
        "    image: airspace:1.0\n"
        '    ports: ["8080:8080"]\n'
        "    depends_on: [postgres]\n"
        "    environment:\n"
        "      AIRSPACE_DB_URL: postgres://db/airspace\n"
        "      KAFKA_BROKER_URL: kafka:9092\n"
        "    healthcheck:\n"
        '      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]\n'
        "    deploy:\n"
        "      resources:\n"
        "        reservations:\n"
        "          devices:\n"
        "            - driver: nvidia\n"
        "              capabilities: [gpu]\n"
        "  postgres:\n"
        "    image: postgres:16\n"
        '    ports: ["5432:5432"]\n'
        "    volumes:\n"
        "      - pgdata:/var/lib/postgresql/data\n"
        "      - ./init:/docker-entrypoint-initdb.d\n"
        "volumes:\n"
        "  pgdata: {}\n",
        encoding="utf-8",
    )
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_codeingest_extractors.py -k "TestComposeFacts" -q`
Expected: 7 failures, `AssertionError` on the `| Volumes |` / `| Healthcheck |` / `| Devices |` rows.

- [ ] **Step 4: Implement**

In `services.py`, after the `ServiceRecord` dataclass fields (line ~82) add the fields and helpers:

```python
    base_image: str = ""                # FROM of a built service (Task 11); feeds technology
    volumes: list[str] = field(default_factory=list)   # compose named volumes, sorted (spec 2026-09-23 §4)
    healthcheck: str = ""                              # one-line `healthcheck.test`; "" = none; "disabled"
    devices: list[str] = field(default_factory=list)   # "<driver>:<caps>" from deploy.resources.reservations.devices


HEALTHCHECK_MAX = 200
_HEALTHCHECK_DISABLED = "disabled"


def _named_volumes(value: object) -> list[str]:
    """Sources of a compose `volumes:` list that are named volumes: not a
    bind mount (`./`, `/`, `~`), not env-templated (`$`), no `/` at all.
    Long-form mappings contribute `source` when `type` is absent or
    `volume`. Sorted, de-duplicated — never the parse order."""
    if not isinstance(value, list):
        return []
    names: set[str] = set()
    for entry in value:
        if isinstance(entry, str):
            src = entry.split(":", 1)[0].strip()
        elif isinstance(entry, dict):
            if entry.get("type", "volume") != "volume":
                continue
            src = str(entry.get("source", "")).strip()
        else:
            continue
        if not src or src[0] in "./~$" or "/" in src:
            continue
        names.add(src)
    return sorted(names)


def _healthcheck_line(value: object) -> str:
    """`healthcheck.test` as one shell line: list form drops a leading
    `CMD` / `CMD-SHELL`; string form is taken as is. `disable: true` →
    "disabled". Missing → "". Cut at HEALTHCHECK_MAX with `…`."""
    if not isinstance(value, dict):
        return ""
    if value.get("disable") is True:
        return _HEALTHCHECK_DISABLED
    test = value.get("test")
    if isinstance(test, list):
        parts = [str(p) for p in test]
        if parts and parts[0] in ("CMD", "CMD-SHELL"):
            parts = parts[1:]
        line = " ".join(parts)
    elif isinstance(test, str):
        line = test
    else:
        return ""
    line = " ".join(redact_userinfo(line).split())
    if len(line) > HEALTHCHECK_MAX:
        line = line[:HEALTHCHECK_MAX] + "…"
    return line


def _devices(spec: dict) -> list[str]:
    """`deploy.resources.reservations.devices[]` as `<driver>:<caps>`;
    a device with no driver reads `unknown`; capabilities sorted and
    comma-joined. Sorted result."""
    deploy = spec.get("deploy")
    if not isinstance(deploy, dict):
        return []
    devices = (
        deploy.get("resources", {}).get("reservations", {}).get("devices", [])
        if isinstance(deploy.get("resources"), dict)
        and isinstance(deploy["resources"].get("reservations"), dict)
        else []
    )
    out: list[str] = []
    for dev in devices if isinstance(devices, list) else []:
        if not isinstance(dev, dict):
            continue
        driver = str(dev.get("driver") or "unknown")
        caps = dev.get("capabilities", [])
        caps_str = ",".join(sorted(str(c) for c in caps)) if isinstance(caps, list) else str(caps)
        out.append(f"{driver}:{caps_str}" if caps_str else driver)
    return sorted(out)
```

In the compose reader, extend the `records.append(ServiceRecord(...))` call (line ~284):

```python
            records.append(ServiceRecord(
                name=str(name),
                image=image,
                ports=ports,
                depends_on=_stringify_list(spec.get("depends_on", [])),
                env_keys=_env_keys_from(spec.get("environment", {})),
                source=source,
                command=command,
                env_files=_stringify_list(spec.get("env_file", [])),
                base_image=base_image,
                volumes=_named_volumes(spec.get("volumes")),
                healthcheck=_healthcheck_line(spec.get("healthcheck")),
                devices=_devices(spec),
            ))
```

In `_render_section`, after the `| Env file |` row and before `| Source |`:

```python
        f"| Volumes | {escape_cell(', '.join(record.volumes)) or 'none'} |",
        f"| Healthcheck | {escape_cell(record.healthcheck) or 'none'} |",
        f"| Devices | {escape_cell(', '.join(record.devices)) or 'none'} |",
```

And in `record_dict`, directly after `"env_keys": record.env_keys,`:

```python
        "volumes": record.volumes,
        "healthcheck": record.healthcheck or "none",
        "devices": record.devices,
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_codeingest_extractors.py tests/test_ticketcheck.py tests/test_cli_ticket_check.py -q`
Expected: all pass. If a pre-existing extractor test asserts an exact `l3_md` for a compose service, it will now fail on the three new keys — update that assertion to include them (they are the intended change), do not weaken the test.

- [ ] **Step 6: Commit**

```bash
node .gitnexus/run.cjs detect-changes --scope all --repo .
git add src/strata_kb/codeingest/extractors/services.py tests/fixtures_coderepo.py tests/test_codeingest_extractors.py
git commit -m "feat(code-ingest): svc.* carries named volumes, healthcheck command and device reservations

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: `kb ticket check` — `Volumes:` / `Healthchecks:` / `Devices:` lines

**Files:**
- Modify: `src/strata_kb/ticketcheck.py:285-325` (`check()`), `:375-384` (`_id_lines`), append `_check_compose_facts` after `_check_tables_routes_commands`
- Test: `tests/test_ticketcheck.py`

**Interfaces:**
- Consumes: L2 rows `| Volumes | … |`, `| Healthcheck | … |`, `| Devices | … |` from Task 1 (fixture: `svc.airspace-service` → volumes `none`, healthcheck `curl -f http://localhost:8080/health`, devices `nvidia:gpu`; `svc.postgres` → volumes `pgdata`, healthcheck `none`, devices `none`).
- Produces: `COMPOSE_FIELDS = ("Volumes", "Healthchecks", "Devices")`; `_check_compose_facts(section, doc, decisions, issues, notes)`; grounding line grammar `- <Field>: svc.<a> — v1, v2; svc.<b> — none` or `- <Field>: none`.

- [ ] **Step 1: Impact analysis**

```bash
node .gitnexus/run.cjs impact "check" --direction upstream --repo .
node .gitnexus/run.cjs impact "_id_lines" --direction upstream --repo .
```
Expected callers: `cli.ticket_check`, `_check_ids`, `_check_tables_routes_commands`.

- [ ] **Step 2: Write the failing tests**

In `tests/test_ticketcheck.py`, extend `DEFAULTS` by appending **after** `"Open decisions"` (keeps every existing `(line N)` assertion valid):

```python
    "Open decisions": ["none"],
    "Volumes": "svc.airspace-service — none",
    "Healthchecks": "svc.airspace-service — `curl -f http://localhost:8080/health`",
    "Devices": "svc.airspace-service — nvidia:gpu",
}
```

Append tests:

```python
# --- compose facts: Volumes / Healthchecks / Devices (spec 2026-09-23) ----

TWO_SVC = "svc.airspace-service, svc.postgres"


def test_golden_compose_facts_pass(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev)), kb_dir)
    assert errors(report) == [], report.render("Grounding")
    assert not any("Volumes:/Healthchecks:/Devices:" in w for w in warnings(report))


def test_volume_not_on_the_service_is_an_error(code_doc):
    kb_dir, rev = code_doc
    bad = run(ticket(grounding(rev, Service=TWO_SVC, Volumes="svc.postgres — myflix-postgres-data")), kb_dir)
    assert any(e == "volume 'myflix-postgres-data' is not in svc.postgres (has: pgdata) (line 17)" for e in errors(bad))
    good = run(ticket(grounding(rev, Service=TWO_SVC, Volumes="svc.postgres — pgdata")), kb_dir)
    assert not any("volume" in e for e in errors(good))


def test_healthcheck_must_match_verbatim(code_doc):
    kb_dir, rev = code_doc
    bad = run(ticket(grounding(rev, Healthchecks="svc.airspace-service — `curl -f http://localhost:8080/api/health`")), kb_dir)
    assert any(
        e == "healthcheck for svc.airspace-service is 'curl -f http://localhost:8080/health', not 'curl -f http://localhost:8080/api/health' (line 18)"
        for e in errors(bad)
    )
    none_bad = run(ticket(grounding(rev, Service=TWO_SVC, Healthchecks="svc.airspace-service — `curl -f http://localhost:8080/health`; svc.postgres — `pg_isready`")), kb_dir)
    assert any("healthcheck for svc.postgres is 'none'" in e for e in errors(none_bad))
    none_good = run(ticket(grounding(rev, Service=TWO_SVC, Healthchecks="svc.airspace-service — `curl -f http://localhost:8080/health`; svc.postgres — none")), kb_dir)
    assert not any("healthcheck" in e for e in errors(none_good))


def test_healthcheck_url_is_never_read_as_a_section_id(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev, Healthchecks="svc.airspace-service — `curl -f http://api.internal/health`")), kb_dir)
    assert not any("unknown id 'api.internal" in e for e in errors(report))


def test_device_not_on_the_service_is_an_error(code_doc):
    kb_dir, rev = code_doc
    bad = run(ticket(grounding(rev, Service=TWO_SVC, Devices="svc.postgres — nvidia:gpu")), kb_dir)
    assert any(e == "device 'nvidia:gpu' is not in svc.postgres (has: none) (line 19)" for e in errors(bad))


def test_new_marker_exempts_a_compose_value(code_doc):
    kb_dir, rev = code_doc
    report = run(
        ticket(grounding(rev, Service=TWO_SVC, Volumes="svc.postgres — pgdata, myflix-minio-data [NEW: D1]"), parent="M-demo"),
        kb_dir, load_decisions=decisions_of(MISSION),
    )
    assert not any("volume" in e for e in errors(report))
    assert any("new: myflix-minio-data — D1 (DECIDED" in n for n in notes(report))


def test_svc_on_a_compose_line_must_be_on_the_service_line(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev, Volumes="svc.postgres — pgdata")), kb_dir)
    assert any(e == "svc.postgres on the Volumes: line is not on the Service: line (line 17)" for e in errors(report))


def test_whole_line_none_while_the_service_has_volumes_warns(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev, Service=TWO_SVC, Volumes="none")), kb_dir)
    assert errors(report) == []
    assert any(w == "svc.postgres has volumes the grounding omits: pgdata (line 17)" for w in warnings(report))


def test_missing_compose_lines_are_a_warning_not_an_error(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev, Volumes=None, Healthchecks=None, Devices=None)), kb_dir)
    assert errors(report) == []
    assert any(w == "Volumes:/Healthchecks:/Devices: lines missing — re-ground on a -code revision that carries them" for w in warnings(report))


def test_old_code_doc_without_the_rows_skips_with_a_note(code_doc, tmp_path):
    kb_dir, rev = code_doc
    services_md = kb_dir / "demo-code" / "services.md"
    text = services_md.read_text(encoding="utf-8")
    text = "\n".join(l for l in text.splitlines() if not l.startswith(("| Volumes |", "| Healthcheck |", "| Devices |")))
    services_md.write_text(text + "\n", encoding="utf-8")
    report = run(ticket(grounding(rev, Volumes="svc.airspace-service — ghost")), kb_dir)
    assert not any("volume" in e for e in errors(report))
    assert any(n == "demo-code has no Volumes/Healthcheck/Devices rows (pre-1.3.0 code-ingest) — compose-fact checks skipped" for n in notes(report))
```

Line arithmetic for the assertions: title 1, blank 2, `## Summary` 3, body 4, blank 5, heading 6, `Grounded on` 7, `Service` 8, `Files:` 9, path 10, `Tables` 11, `Routes` 12, `Externals` 13, `Verify with` 14, `Open decisions:` 15, `- none` 16, `Volumes` 17, `Healthchecks` 18, `Devices` 19.

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_ticketcheck.py -q -k "compose or volume or healthcheck or device or none_while or missing_compose or old_code_doc"`
Expected: FAIL — no compose errors/warnings/notes are produced yet; `test_healthcheck_url_is_never_read_as_a_section_id` fails with `unknown id 'api.internal'`.

- [ ] **Step 4: Implement**

Constants, near `_NONE_WORDS`:

```python
COMPOSE_FIELDS: tuple[str, ...] = ("Volumes", "Healthchecks", "Devices")
# `svc.<x> — <values>` groups on one compose line, `;`-separated.
_COMPOSE_GROUP_RE = re.compile(r"(svc\.[A-Za-z0-9_][A-Za-z0-9_.-]*)\s*[—-]\s*(?P<values>[^;]*)")
_COMPOSE_ROW = {"Volumes": "Volumes", "Healthchecks": "Healthcheck", "Devices": "Devices"}
_COMPOSE_NOUN = {"Volumes": "volume", "Healthchecks": "healthcheck", "Devices": "device"}
```

`_id_lines` — strip code spans on the `Healthchecks` field so a URL such as `http://api.internal/health` is never matched by `ID_RE`:

```python
def _id_lines(section: _Section):
    for i, line in enumerate(section.lines):
        if section.field_of_line[i] in ("Grounded on", "Files"):
            continue
        if section.field_of_line[i] == "Healthchecks":
            line = CODE_SPAN_RE.sub("``", line)
        if line.strip():
            yield section.first_line + i, line
```

The check, appended after `_check_tables_routes_commands`:

```python
def _service_ids(section: _Section) -> set[str]:
    ids: set[str] = set()
    for i, line in enumerate(section.lines):
        if section.field_of_line[i] == "Service":
            ids |= {s for s in ID_RE.findall(line) if s.startswith("svc.")}
    return ids


def _field_lines(section: _Section, name: str) -> list[tuple[int, str]]:
    """(lineno, rest) for the `- <name>: <rest>` line plus its sub-bullets."""
    out: list[tuple[int, str]] = []
    for i, line in enumerate(section.lines):
        if section.field_of_line[i] == name and not line[:1].isspace():
            m = FIELD_RE.match(line)
            if m is not None and m.group("rest").strip():
                out.append((section.first_line + i, m.group("rest").strip()))
    out += section.subitems.get(name, [])
    return out


def _property(rows: list[list[str]], name: str) -> str | None:
    """The `Value` cell of the L2 property row named `name`, pipes unescaped."""
    for r in rows[1:]:
        if len(r) >= 2 and r[0].strip() == name:
            return r[1].strip().replace("\\|", "|")
    return None


def _svc_facts(doc: LoadedDoc, sid: str, field: str, unreadable: set[str], issues: list[Issue]) -> set[str] | None:
    """The svc's values for one compose field as a set: `{"pgdata"}`,
    `{"curl -f …"}`, `set()` for `none`. None when unreadable or when the
    document predates the rows (caller skips with a note)."""
    body = _l2_slice(doc, sid, unreadable, issues)
    if body is None:
        return None
    cell = _property(lintcore.table_rows(body), _COMPOSE_ROW[field])
    if cell is None:
        return None
    if cell.casefold() == "none":
        return set()
    if field == "Healthchecks":
        return {cell}
    return {v.strip() for v in cell.split(",") if v.strip()}


def _split_values(field: str, raw: str) -> list[str]:
    raw = raw.strip()
    if field == "Healthchecks":
        spans = CODE_SPAN_RE.findall(raw)
        return spans if spans else [raw]
    return [v.strip().strip("`") for v in raw.split(",") if v.strip()]


def _check_compose_facts(section: _Section, doc: LoadedDoc, decisions: _Decisions,
                         issues: list[Issue], notes: list[str]) -> None:
    present = [f for f in COMPOSE_FIELDS if _field_lines(section, f)]
    if len(present) < len(COMPOSE_FIELDS):
        issues.append(Issue("warning", "Volumes:/Healthchecks:/Devices: lines missing — re-ground on a -code revision that carries them"))
    if not present:
        return
    services = _service_ids(section)
    unreadable: set[str] = set()
    skipped = False
    for field in present:
        for lineno, rest in _field_lines(section, field):
            noun = _COMPOSE_NOUN[field]
            if rest.strip().casefold() in _NONE_WORDS:
                for sid in sorted(services):
                    facts = _svc_facts(doc, sid, field, unreadable, issues)
                    if facts is None:
                        skipped = True
                    elif facts:
                        issues.append(Issue("warning", f"{sid} has {noun}s the grounding omits: {', '.join(sorted(facts))} (line {lineno})"))
                continue
            for g in _COMPOSE_GROUP_RE.finditer(rest):
                sid = g.group(1).rstrip(".")
                if sid not in services:
                    issues.append(Issue("error", f"{sid} on the {field}: line is not on the Service: line (line {lineno})"))
                    continue
                facts = _svc_facts(doc, sid, field, unreadable, issues)
                if facts is None:
                    skipped = True
                    continue
                values_raw = g.group("values")
                if values_raw.strip().casefold() in _NONE_WORDS:
                    if facts:
                        issues.append(Issue("error", f"{noun} for {sid} is '{', '.join(sorted(facts))}', not 'none' (line {lineno})"))
                    continue
                for value in _split_values(field, values_raw):
                    new = NEW_RE.search(value)
                    if new is not None:
                        _judge_new(NEW_RE.sub("", value).strip(), new, lineno, decisions, issues, notes)
                        continue
                    if value in facts:
                        continue
                    have = ", ".join(sorted(facts)) or "none"
                    if field == "Healthchecks":
                        issues.append(Issue("error", f"healthcheck for {sid} is '{have}', not '{value}' (line {lineno})"))
                    else:
                        issues.append(Issue("error", f"{noun} '{value}' is not in {sid} (has: {have}) (line {lineno})"))
    if skipped:
        notes.append(f"{doc.manifest.id} has no Volumes/Healthcheck/Devices rows (pre-1.3.0 code-ingest) — compose-fact checks skipped")
```

Wire it in `check()` after `_check_tables_routes_commands(section, doc, issues)`:

```python
    _check_tables_routes_commands(section, doc, issues)
    if heading != SERVICES_HEADING:
        _check_compose_facts(section, doc, decisions, issues, notes)
    _check_files(section, doc, decisions, issues, notes)
```

Note on `_judge_new` inside a `[NEW: D1]` value: the group regex stops at `;` so `pgdata, myflix-minio-data [NEW: D1]` splits into `pgdata` and `myflix-minio-data [NEW: D1]`; the marker exempts only the value it sits on.

Update the module docstring's first paragraph to name the three lines: after "`Files:` must be listed in `struct.tree`," add "`Volumes:` / `Healthchecks:` / `Devices:` must match the svc L2 rows,".

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_ticketcheck.py tests/test_cli_ticket_check.py -q`
Expected: all pass, including the pre-existing line-number assertions (nothing above `Open decisions` moved).

- [ ] **Step 6: Commit**

```bash
node .gitnexus/run.cjs detect-changes --scope all --repo .
git add src/strata_kb/ticketcheck.py tests/test_ticketcheck.py
git commit -m "feat(ticket-check): verify Volumes:/Healthchecks:/Devices: grounding lines against svc.* facts

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: `kb ticket lint` — an AC that prescribes a shell command warns

**Files:**
- Modify: `src/strata_kb/ticketlint.py` (constants near `_AC_ITEM_RE`; `_check_ac_shell` after `_check_ac_weasel`; one call in `lint()`)
- Test: `tests/test_ticketlint.py`

**Interfaces:**
- Produces: `SHELL_COMMANDS: frozenset[str]`, `_check_ac_shell(ac_items: list[str]) -> list[Issue]`. Message shape: `AC<n> prescribes a shell command (\`<span>\`) — state the observable outcome here; the command belongs in ## Test data & verification or the Dev's plan — see docs/ac-quality.md`.

- [ ] **Step 1: Impact analysis**

```bash
node .gitnexus/run.cjs impact "lint" --direction upstream --repo .
```
Expected callers: `cli.ticket_lint`, the `kb_ticket_lint` MCP tool, `ticket_lint` CI helpers.

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_ticketlint.py`:

```python
# --- shell commands in an AC (spec 2026-09-23 §6) ---

def _ac_report(fed_hub: Path, golden_block: str, ac_lines: str):
    doc = _build_ticket(golden_block, overrides={"## Acceptance Criteria": ac_lines})
    return ticketlint.lint(doc, _hub(fed_hub))


def test_ac_with_a_shell_command_warns(fed_hub: Path, golden_block: str):
    report = _ac_report(
        fed_hub, golden_block,
        "- [ ] AC1 — `docker compose up -d --wait` exits 0 per [arinc-kb:arinc-424 §5.3]\n"
        "- [ ] AC2 — Every service reports healthy per [icao-kb:icao-annex-2 §1.1]",
    )
    assert report.passed is True
    hits = [w for w in _warnings(report) if "prescribes a shell command" in w]
    assert len(hits) == 1
    assert hits[0].startswith("AC1 prescribes a shell command (`docker compose up -d --wait`)")
    assert "## Test data & verification" in hits[0]


def test_ac_with_a_pipe_between_words_warns(fed_hub: Path, golden_block: str):
    report = _ac_report(
        fed_hub, golden_block,
        "- [ ] AC1 — output of `something | jq .` is valid per [arinc-kb:arinc-424 §5.3]\n"
        "- [ ] AC2 — Second per [icao-kb:icao-annex-2 §1.1]",
    )
    assert any("AC1 prescribes a shell command" in w for w in _warnings(report))


def test_backticked_names_and_values_do_not_warn(fed_hub: Path, golden_block: str):
    report = _ac_report(
        fed_hub, golden_block,
        "- [ ] AC1 — `nginx` publishes port `80`; `.env.example` lists `POSTGRES_DB`; encoder is `h264_nvenc` per [arinc-kb:arinc-424 §5.3]\n"
        "- [ ] AC2 — Second per [icao-kb:icao-annex-2 §1.1]",
    )
    assert not any("prescribes a shell command" in w for w in _warnings(report))


def test_owned_open_marker_suppresses_the_shell_warning(fed_hub: Path, golden_block: str):
    report = _ac_report(
        fed_hub, golden_block,
        "- [ ] AC1 — `curl -f http://localhost/health` returns 200 OPEN(BA) per [arinc-kb:arinc-424 §5.3]\n"
        "- [ ] AC2 — Second per [icao-kb:icao-annex-2 §1.1]",
    )
    assert not any("prescribes a shell command" in w for w in _warnings(report))
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_ticketlint.py -q -k "shell or pipe_between or backticked_names or suppresses_the_shell"`
Expected: 2 FAIL (`warns` tests find no hit), 2 PASS (negative tests pass trivially — that is fine; they guard Step 4).

- [ ] **Step 4: Implement**

Constants after `_AC_ITEM_RE`:

```python
# An AC is an observable outcome, never a shell command (docs/ac-quality.md,
# spec 2026-09-23 §6). A backticked span whose first word is one of these,
# or that chains two words with a shell operator, is the command a Dev
# would run — it belongs in `## Test data & verification` or the plan.
SHELL_COMMANDS: frozenset[str] = frozenset({
    "docker", "docker-compose", "curl", "wget", "grep", "psql", "redis-cli",
    "ffmpeg", "ffprobe", "mc", "kubectl", "npm", "pnpm", "npx", "prisma",
    "ls", "cat", "find", "nvidia-smi", "sh", "bash",
})
_CODE_SPAN_RE = re.compile(r"`([^`]+)`")
_SHELL_OPERATOR_RE = re.compile(r"\S\s+(\|\||\||&&|;)\s+\S")
_AC_ID_PREFIX_RE = re.compile(r"^\s*(AC\d+)")
```

Function after `_check_ac_weasel`:

```python
def _is_shell_span(span: str) -> bool:
    first = span.strip().split(maxsplit=1)[0] if span.strip() else ""
    return first in SHELL_COMMANDS or _SHELL_OPERATOR_RE.search(span) is not None


def _check_ac_shell(ac_items: list[str]) -> list[Issue]:
    """An AC that prescribes a shell command shifts the guess about the
    real image/tool/path onto the BA, who cannot run it. Warning per AC
    (first offending span); an owned OPEN(<owner>) on the line suppresses
    it, as for weasel words."""
    issues: list[Issue] = []
    for item in ac_items:
        if acquality.owned_open_markers(item):
            continue
        span = next((s for s in _CODE_SPAN_RE.findall(item) if _is_shell_span(s)), None)
        if span is None:
            continue
        m = _AC_ID_PREFIX_RE.match(item)
        label = m.group(1) if m else "AC"
        issues.append(Issue(
            "warning",
            f"{label} prescribes a shell command (`{span}`) — state the observable "
            "outcome here; the command belongs in ## Test data & verification or "
            "the Dev's plan — see docs/ac-quality.md",
        ))
    return issues
```

In `lint()`, directly after `issues += _check_ac_weasel(ac_items)`:

```python
    issues += _check_ac_shell(ac_items)
```

Check `acquality.owned_open_markers(text)` returns a non-empty list for `OPEN(BA)` and empty for `OPEN(TBD)` / no marker (it does — `_marker_is_owned`). If `ac_items` entries carry the leading `- [ ] ` prefix in this module, strip it before `_AC_ID_PREFIX_RE` with `_AC_ITEM_RE.match(item)`; check how `_check_ac_ids` reads the id and mirror it.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_ticketlint.py -q`
Expected: all pass; the golden ticket still passes (its ACs carry no shell spans — verify with the run).

- [ ] **Step 6: Commit**

```bash
node .gitnexus/run.cjs detect-changes --scope all --repo .
git add src/strata_kb/ticketlint.py tests/test_ticketlint.py
git commit -m "feat(ticket-lint): warn when an acceptance criterion prescribes a shell command

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Ticket template and `ac-quality.md`

**Files:**
- Modify: `src/strata_kb/templates/init/ticket-template.md` (Technical grounding block, DoR last item)
- Modify: `src/strata_kb/templates/init/ac-quality.md` (table row)
- Test: `tests/test_templates.py`

**Interfaces:**
- Produces: the exact template lines Task 6's SA skill text refers to.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_templates.py`:

```python
# --- compose facts grounding (spec 2026-09-23) ---

def test_ticket_template_carries_the_compose_grounding_lines():
    text = _read_init_template("ticket-template.md")
    for needle in (
        "- Volumes: svc.<name> — <volume>, … — or `none`",
        "- Healthchecks: svc.<name> — `<test command>`; svc.<name> — none — or `none`",
        "- Devices: svc.<name> — <driver:caps> — or `none`",
        "no value in an AC rests on a `DECIDED` note instead of a section id or a D-row",
    ):
        assert needle in text, needle


def test_ac_quality_doc_bans_shell_commands_in_an_ac():
    text = _read_init_template("ac-quality.md")
    assert "a shell command in the AC" in text
    assert "`## Test data & verification`" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_templates.py -q -k "compose_grounding_lines or bans_shell"`
Expected: 2 FAIL.

- [ ] **Step 3: Edit the templates**

`ticket-template.md`, in `## Technical grounding`, after the `- Externals:` line insert:

```
- Volumes: svc.<name> — <volume>, … — or `none`
- Healthchecks: svc.<name> — `<test command>`; svc.<name> — none — or `none`
- Devices: svc.<name> — <driver:caps> — or `none`
```

Extend the section's HTML comment: after "Gate:" sentence add "`Volumes:` / `Healthchecks:` / `Devices:` are copied from the svc records' own rows; a volume or device the ticket creates carries `[NEW: D<n>]`."

Replace the DoR last item:

```
- [ ] Technical grounding filled by SA; kb ticket check PASS; Open decisions empty; no value in an AC rests on a `DECIDED` note instead of a section id or a D-row
```

`ac-quality.md`, append a table row (backticks only, no double quotes):

```
| a shell command in the AC (`docker compose ps …`, `curl …`, `grep …`) | the observable outcome (`every service reports healthy`, `no secret value is committed`); the exact command goes to `## Test data & verification`, or the Dev writes it in the plan where it can be run |
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_templates.py tests/test_init.py tests/test_ticketlint.py -q`
Expected: all pass (`test_every_quoted_doc_phrase_is_in_the_detector` untouched because the new row has no `"`).

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/templates/init/ticket-template.md src/strata_kb/templates/init/ac-quality.md tests/test_templates.py
git commit -m "feat(templates): Volumes/Healthchecks/Devices grounding lines, DoR item, no-shell AC rule

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Review rubric and quickstarts

**Files:**
- Modify: `src/strata_kb/templates/init/review-rubric.md` (Dev implementability list)
- Modify: `src/strata_kb/templates/init/QUICKSTART-ba.md:57-60`, `QUICKSTART-dev.md:250-252`
- Test: `tests/test_templates.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_templates.py`:

```python
def test_review_rubric_dev_axis_checks_compose_literals_against_grounding():
    text = _read_init_template("review-rubric.md")
    assert "matches the value on the corresponding `## Technical grounding` line, or carries `[NEW: D<n>]`" in text


def test_quickstarts_name_the_compose_facts():
    ba = _read_init_template("QUICKSTART-ba.md")
    dev = _read_init_template("QUICKSTART-dev.md")
    assert "volumes, healthcheck commands and device reservations" in ba
    assert "`Volumes:` / `Healthchecks:` / `Devices:`" in ba
    assert "named volumes, the healthcheck command and device reservations" in dev
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_templates.py -q -k "compose_literals or name_the_compose"`
Expected: 2 FAIL.

- [ ] **Step 3: Edit**

`review-rubric.md`, `## Dev implementability` checklist, insert before `- [ ] No weasel words anywhere in the body.`:

```
- [ ] Every compose-level literal in an AC — volume name, published port
      and bind address, image tag, healthcheck command, device
      reservation — matches the value on the corresponding `## Technical
      grounding` line, or carries `[NEW: D<n>]`. A mismatch is a gap
      owned by the BA.
```

`QUICKSTART-ba.md`, step 7 paragraph: replace "(service, files, tables, routes, externals, test command — section ids only)" with "(service, files, tables, routes, externals, volumes, healthcheck commands and device reservations, test command — section ids and copied values only)". After the sentence ending "in the handover." add:

```
      The `Volumes:` / `Healthchecks:` / `Devices:` lines are copied from the
      `<repo>-code` svc records and checked by `kb ticket check`; a value the
      document does not carry is `[NEW: D<n>]` or an Open decision — never a
      `DECIDED` note folded into an AC.
```

`QUICKSTART-dev.md`, `<repo_id>-code` bullet, after "so it always reflects the current commit's structure." add:

```
  Since 1.3.0 each `svc.*` record also carries its named volumes, the
  healthcheck command and device reservations from compose, so the SA
  grounds those instead of deciding them — run CI once (any merge) after
  upgrading before the BA re-grounds.
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_templates.py tests/test_init.py tests/test_cli_ticket_check.py -q`
Expected: all pass (`test_docs_name_the_check_command` still finds its `kb ticket check` line in QUICKSTART-ba).

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/templates/init/review-rubric.md src/strata_kb/templates/init/QUICKSTART-ba.md src/strata_kb/templates/init/QUICKSTART-dev.md tests/test_templates.py
git commit -m "docs(templates): rubric item for compose literals; quickstarts name the new svc facts

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: `sa-ticket-ground` wrappers — Load, Fill, hard rule

**Files:**
- Modify: `src/strata_kb/templates/init/claude-skill-sa-ticket-ground.md` (step 2 Load, step 3 Fill bullets, `## Hard rules`)
- Derive: `copilot-sa-ticket-ground.prompt.md`, `cursor-sa-ticket-ground.md`
- Test: `tests/test_sa_ticket_ground.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_sa_ticket_ground.py`, extend `SA_HARD_RULE_NEEDLES`:

```python
SA_HARD_RULE_NEEDLES = (
    "Grounded on:",
    "Open decisions",
    "[NEW:",
    "kb ticket check",
    "internal flow",
    "failure modes",
    "BA-owned section",
    "is not a PASS",
    "Definition of Ready",
    "`Volumes:`",
    "`Healthchecks:`",
    "`Devices:`",
    "`DECIDED` is not a status of this gate",
    "never goes into an AC as a description of the current state",
)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_sa_ticket_ground.py -q`
Expected: `test_sa_wrappers_carry_the_grounding_hard_rules` FAILS for all 4 wrappers on `` `Volumes:` ``.

- [ ] **Step 3: Edit the claude skill**

Step 2 **Load**: after "every `svc.*`, `cmd.test`, and the `db.*` / `api.*` / `int.*` sections whose names match the ticket's nouns." add: "From each `svc.*` also read its `Volumes`, `Healthcheck` and `Devices` rows — the compose facts the ticket's ACs are most often wrong about."

Step 3 **Fill**, after the `- Externals:` bullet insert three bullets:

```
   - `Volumes:` — `svc.<name> — <volume>, …` copied from the record's
     `Volumes` row; `svc.<name> — none` when the row says `none`; a
     volume the ticket creates: `<name> [NEW: D<n>]`. Whole line `none`
     only when no touched service has a volume.
   - `Healthchecks:` — `svc.<name> — \`<test command>\`` byte for byte
     from the `Healthcheck` row, or `svc.<name> — none` / `disabled` as
     the row says; several services `;`-separated on one line.
   - `Devices:` — `svc.<name> — <driver:caps>` from the `Devices` row,
     or `none`.
```

`## Hard rules`, append:

```
- A value for a field the document does not carry has exactly two
  homes: `[NEW: D<n>]` when the ticket intends to create or change it,
  or `Open decisions` when the document simply cannot prove it. It
  never goes into an AC as a description of the current state.
  `DECIDED` is not a status of this gate — closing an Open decision
  requires a section id or a D-row, nothing else.
```

- [ ] **Step 4: Derive the copilot and cursor wrappers**

```bash
uv run python - <<'EOF'
from pathlib import Path
base = Path("src/strata_kb/templates/init")
body = (base / "claude-skill-sa-ticket-ground.md").read_text(encoding="utf-8").split("\n---\n", 1)[1]
for name in ("copilot-sa-ticket-ground.prompt.md", "cursor-sa-ticket-ground.md"):
    p = base / name
    fm = p.read_text(encoding="utf-8").split("\n---\n", 1)[0]
    p.write_text(fm + "\n---\n" + body, encoding="utf-8")
EOF
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_sa_ticket_ground.py tests/test_templates.py tests/test_cli_ticket_check.py -q`
Expected: all pass, including `test_sa_full_wrappers_are_byte_identical_after_frontmatter` and `test_copilot_and_cursor_sa_wrappers_differ_only_on_frontmatter_line_2`.

- [ ] **Step 6: Commit**

```bash
git add src/strata_kb/templates/init/*sa-ticket-ground* tests/test_sa_ticket_ground.py
git commit -m "feat(sa-ticket-ground): ground volumes, healthchecks and devices; DECIDED is not a gate status

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: `ba-ticket-author` wrappers — no shell in an AC; no score without a reviewer

**Files:**
- Modify: `src/strata_kb/templates/init/claude-skill-ba-ticket-author.md` (step 4 Draft, step 8 Maturity review)
- Modify: `src/strata_kb/templates/init/copilot-ba-ticket-author.prompt.md` (same two insertions)
- Derive: `cursor-ba-ticket-author.md` from copilot
- Test: `tests/test_templates.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
@pytest.mark.parametrize("name", [
    "claude-skill-ba-ticket-author.md",
    "copilot-ba-ticket-author.prompt.md",
    "cursor-ba-ticket-author.md",
])
def test_ba_ticket_author_wrappers_carry_the_no_shell_and_no_rescore_rules(name):
    text = _normalised(_read_init_template(name))
    assert "An AC states an observable outcome, never a shell command" in text
    assert "A round that only closes open questions is not a review round and never changes a score" in text
```

(`pytest` is already imported at the top of `tests/test_templates.py`; if not, add `import pytest`.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_templates.py -q -k "no_shell_and_no_rescore"`
Expected: 3 FAIL.

- [ ] **Step 3: Edit claude and copilot**

In both files, step 4 **Draft**, at the end of the **AC quality bar** paragraph (after "never merge ACs to fit.") append:

```
   An AC states an observable outcome, never a shell command
   (`docker compose …`, `curl …`, `grep …`); the exact command goes to
   `## Test data & verification`, where the Dev can run it against the
   real images — `kb ticket lint` warns on the former.
```

Step 8 **Maturity review**, after the paragraph ending "otherwise carry the previous round's score forward unchanged." insert:

```
   A round that only closes open questions is not a review round and
   never changes a score. A score rises only when a `gap-verifier`
   (rounds 2–3) or the two reviewers (round 1) record PASS on every gap
   of that axis. Re-deriving a score by hand is forbidden; a closed
   question the reviewers never saw is a `DECIDED` note, not a fact, and
   stays out of the ACs until the SA's `## Technical grounding` or a
   D-row carries it.
```

- [ ] **Step 4: Derive cursor from copilot**

```bash
uv run python - <<'EOF'
from pathlib import Path
base = Path("src/strata_kb/templates/init")
src = (base / "copilot-ba-ticket-author.prompt.md").read_text(encoding="utf-8").splitlines(keepends=True)
dst = base / "cursor-ba-ticket-author.md"
cur = dst.read_text(encoding="utf-8").splitlines(keepends=True)
assert src[1] == "mode: agent\n" and cur[1] == "name: ba-ticket-author\n"
dst.write_text("".join(src[:1] + cur[1:2] + src[2:]), encoding="utf-8")
EOF
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_templates.py tests/test_init.py -q`
Expected: all pass, including `test_ba_ticket_author_templates_pin_the_parallel_vs_sequential_split` (the copilot/cursor bodies still carry their sequential-fallback wording; only the claude skill differs there, as before).

- [ ] **Step 6: Commit**

```bash
git add src/strata_kb/templates/init/*ba-ticket-author* tests/test_templates.py
git commit -m "feat(ba-ticket-author): ACs state outcomes not shell; no score change without a reviewer

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Changelog, version, manual verification on MyFlix

**Files:**
- Modify: `CHANGELOG.md` (new top entry), `pyproject.toml:3`

- [ ] **Step 1: CHANGELOG entry** — insert above `## 1.2.0 — 2026-09-22`:

```markdown
## 1.3.0 — <today's date>

- `kb code-ingest`: every compose `svc.*` record now carries `volumes` (named volumes only, sorted), `healthcheck` (the `test` command as one line, `none`, or `disabled`, cut at 200 characters) and `devices` (`<driver>:<caps>` from `deploy.resources.reservations.devices`), in the L2 property table and the L3 YAML block. Dockerfile/k8s records leave them empty. The document changes on the next CI run — that new revision is what the SA re-grounds on.
- `kb ticket check` verifies three new `## Technical grounding` lines — `Volumes:`, `Healthchecks:`, `Devices:` — against those rows, as it already verifies routes and columns: a value the service does not have is an error, `[NEW: D<n>]` exempts a value the ticket creates, a whole-line `none` while the service has volumes is a warning. Tickets written before 1.3.0 (no such lines) get one warning, never an error; a `-code` document generated before 1.3.0 makes the three checks skip with a note.
- `kb ticket lint` warns when an acceptance criterion prescribes a shell command (`docker compose …`, `curl …`, `grep …`, a pipe between words). An AC states the observable outcome; the command belongs in `## Test data & verification` or the Dev's plan. Suppressed on a line with an owned `OPEN(<owner>)`. `docs/ac-quality.md` gains the row.
- BA repos: `sa-ticket-ground` copies the three new lines and may no longer fold a value the document lacks into an AC — `[NEW: D<n>]` or `Open decisions`, nothing else; `ba-ticket-author` writes outcome-level ACs and never changes a maturity score in a round with no reviewer; the review rubric's Dev axis checks every compose literal in an AC against the grounding; the ticket template's Definition of Ready says the same. Re-run `kb init --kind ba` to pick up the new template text.
```

- [ ] **Step 2: Version bump** — `pyproject.toml` line 3: `version = "1.3.0"`. Run `uv lock` if the lockfile records the project version (check `git diff uv.lock` — commit it only if it changed).

- [ ] **Step 3: Full suite**

Run: `uv run pytest -q`
Expected: all green. Paste the summary line into the PR description.

- [ ] **Step 4: Manual verification on MyFlix** (records the evidence the spec §9 asks for; nothing in MyFlix is committed)

```bash
cd /Users/vuonglq01685/Documents/Projects/MyFlix/code/myflix
uv run --project /Users/vuonglq01685/Documents/Projects/AERO-KB kb code-ingest
grep -n -A3 "| Volumes |" .kb/myflix-code/services.md | head -40
```
Expected: `svc.postgres` → `| Volumes | pgdata |`; `svc.web` → `| Healthcheck | none |`; `svc.transcoder` → `| Devices | nvidia:… |`; `svc.minio` → `| Healthcheck | mc ready local |` (or whatever compose says — record what it says).

Then, in a scratch copy of the ticket (never the BA repo's file):

```bash
cp /Users/vuonglq01685/Documents/Projects/MyFlix/code/myflix-ba/tickets/M-platform-operations-US1.md "$SCRATCH/US1.md"
# add under `- Externals:`:  - Volumes: svc.postgres — myflix-postgres-data
uv run --project /Users/vuonglq01685/Documents/Projects/AERO-KB kb ticket check "$SCRATCH/US1.md" --kb-dir .kb
```
Expected: `[error] volume 'myflix-postgres-data' is not in svc.postgres (has: pgdata) (line N)` and `Grounding: FAIL`. Then `git -C /Users/vuonglq01685/Documents/Projects/MyFlix/code/myflix checkout -- .kb` to discard the regenerated document (CI regenerates it on merge).

Also run `kb ticket lint` on the scratch copy and record the count of `prescribes a shell command` warnings (expected around 20 of 27).

- [ ] **Step 5: Commit**

```bash
node .gitnexus/run.cjs detect-changes --scope all --repo .
git add CHANGELOG.md pyproject.toml
git commit -m "chore: release 1.3.0 — compose facts in -code, grounding lines kb ticket check verifies, no shell in an AC

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

- [ ] **Step 6: PR** — open with `gh pr create` against `main`; body: the §1 evidence table from the spec (8 GAP rows), the four bullets above, the full-suite summary line, and the MyFlix verification output. End the body with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`. Release = squash-merge then tag `v1.3.0` (user's process).

---

## Self-review

- **Spec coverage:** §4 → Task 1; §5 → Task 2 + Task 4 (template); §6 → Task 3 + Task 4 (ac-quality); §7 → Tasks 4 (DoR), 5 (rubric, quickstarts), 6 (SA), 7 (BA); §9 → tests in each task + Task 8 Step 4; §10 → Task 8. Non-goals (§3) untouched.
- **Placeholders:** none; every step carries its code or exact text. `<today's date>` in Task 8 is the only fill-in and is the calendar date.
- **Type consistency:** `ServiceRecord.volumes/healthcheck/devices` (Task 1) ↔ L2 rows `Volumes`/`Healthcheck`/`Devices` read by `_COMPOSE_ROW` (Task 2) ↔ grounding fields `Volumes`/`Healthchecks`/`Devices` (`COMPOSE_FIELDS`, template Task 4, SA skill Task 6). `HEALTHCHECK_MAX` defined once in `services.py`. `_judge_new(label, new, lineno, decisions, issues, notes)` signature reused unchanged.
