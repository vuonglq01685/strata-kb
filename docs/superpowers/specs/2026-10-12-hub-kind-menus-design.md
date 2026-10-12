# Hub kinds — Document / Ticket / Code menus and kind-filtered search

Status: draft for builder check · 2026-10-12

## 1. Intent

The hub shows everything published by every repo in one pile. Documents lists
ingested KB documents next to dev's generated `<rid>-code` and curated
`<rid>-svc`. The top search mixes all of it. `kb query` / `kb_search` cannot
say "only code" or "only tickets"; agents fake it with the doc-id-as-tag trick
(`searchdb.py:569`).

The owner wants the hub split by **who publishes it**, which is the repo's
kind:

| Repo kind (`.kb/config.yaml`) | Hub kind | Menu | What it is |
|---|---|---|---|
| `hub`, `child` | `kb` | **Document** | knowledge-base documents (ingested PDFs, hub-authored docs) |
| `ba` | `ba` | **Ticket** | `<rid>-plan`: missions and tickets (today's Plans menu) |
| `dev` | `dev` | **Code** | `<rid>-code` (generated) and `<rid>-svc` (curated, incl. `hist.*` ticket history per service) |

Why it matters beyond looks: ownership of updates. The code-sync flow
(`kb code-sync`, 1.19.0) updates **Document** content only. `ba` and `dev`
content is only ever updated by publishing from its own repo. Making kind a
first-class, recorded fact makes that boundary visible in the UI and
enforceable in tools.

This is not fixing a reported incident. Success = a reader goes to the menu
for the question they have (docs / tickets / code) and searches only there;
an agent asks for the kind it needs and gets nothing else.

## 2. Goals, non-goals, anti-goals

Goals

1. **Registry has kind.** `federation/registry.yaml` entries carry `kind`
   (`kb | ba | dev`). The hub declares each repo's kind.
2. **Kind travels with content.** Every federation leaf records its kind, so
   nested hubs (child-hub published into a root hub) keep the kinds of the
   repos inside them, which the root registry does not list.
3. **Publish enforces kind.** A publish whose repo kind (from the publisher's
   config) disagrees with the registry entry's kind is rejected.
4. **Upgrade path.** Re-running `kb init --kind hub` on an existing hub fills
   in `kind` for registry entries that lack it and back-fills leaves that lack
   it, then asks the operator to confirm. No directory moves.
5. **UI menus.** Left rail becomes: Overview · Document · Ticket · Code.
   - Plans is renamed Ticket (same pages).
   - The separate "Search" rail item is removed; the top search box stays.
   - Each menu has its own search box that searches only that kind.
   - Overview stays as today, with counts broken down per kind.
6. **Top search = all kinds, option A** (owner's pick from the mockup): one
   mixed list ranked by relevance; each hit carries a kind badge; chips above
   the list (All n · Document n · Ticket n · Code n) narrow it without leaving
   the page.
7. **Query filter.** `kb query --kind <kb|ba|dev>` (repeatable), MCP
   `kb_search(..., kinds=[...])`, and REST `/api/search?kind=` filter by kind.
   No filter = all kinds, exactly as today.
8. **Agents pick the kind.** Skill bodies pass the right filter:
   - BA (`ba-mission-plan`, `ba-ticket-author`): `kb` + `dev` — knowledge plus
     code so tickets are grounded in real code.
   - Dev (`dev-implement-ticket`, `dev-design`, `dev-plan`, `dev-execute`):
     `dev` (own repo's `-code`/`-svc`), `ba`, `kb`.
   - SA (`sa-ticket-ground`): `dev`.
   - Code-sync (`kb-code-sync`): searches `kb` only, since it may only edit
     Document content.

Non-goals

- Moving or renaming anything under `federation/`. Layout stays
  `federation/[<mid>/]<rid>/…`.
- New content. `-svc` already publishes ticket history (`hist.*`, appended by
  `kb svc note`); the Code menu shows it, nothing new is published.
- Access control per kind.
- New kinds beyond `kb | ba | dev`, or one repo spanning several kinds.
- Changing what code-sync does (it already never edits `-code`, `-svc`,
  missions or tickets — `bodies/kb-code-sync.md:18-19`); only its search gets
  `--kind kb`.

Anti-goals (a failure even if it "works")

- Breaking existing hubs or repos on upgrade: an old registry (no `kind`), old
  leaves (no kind recorded), and old clients (no `--kind`) must keep working.
  Unfiltered search must return exactly what it returns today.
- A dev doc showing up in Document, or a KB doc in Code, after upgrade.
- Trusting the publisher for kind on a governed hub: the registry decides,
  the payload is only checked against it.
- A filtered search silently returning unfiltered results (e.g. unknown kind
  value ignored). Unknown kind = error.

## 3. Constraints (verified in the codebase)

- Kinds today: `config.py:57` `kind: Literal["", "hub", "child", "ba", "dev"]`;
  `initcmd.py:21-25` `KINDS`. `""` = unrecorded; `check_kind`
  (`doctor/checks/local.py:192`) warns, and its message still says
  "hub|child" — update it.
- Registry: `models.Registry` (`models.py:198-247`), `repos: dict[str, str |
  RegistryEntry]`, entry `{repo_id, workflow}` with `extra="forbid"`. Read via
  `resolve()` / `federation.registry_map` (`federation.py:63`). Hand-written;
  nothing in code writes it today. Readers: `publish._governed_registry`
  (`publish.py:1150`) → `pubgate.resolve_identity`; `intake.authorize`
  (`intake.py:363-398`). A plain-string entry must stay valid.
- Compat rule already stated in `FedIndexEntry` (`models.py:138-159`): new
  fields optional with defaults, so older readers still load newer files.
- Leaves: a dir with `_meta.yaml` + `index.yaml` (`federation.py:97`).
  `_meta.yaml` = `repo_id, source_url, source_commit, published_at`, written
  by `_snapshot` (`publish.py:452-532`) and the intake path.
- Kind is inferable for legacy content: `<rid>-plan` → `ba`
  (`planstatus.is_plan`, `planstatus.py:46`); `<rid>-code` / `<rid>-svc` →
  `dev`; anything else → `kb`.
- Search DB: `sections` table (`searchdb.py:212`) has `repo_id`; tag filter in
  `fts_search` (`:829-855`). Cache keyed by `SCHEMA_VERSION = "2"`
  (`searchdb.py:56`); a column change bumps it and the cache rebuilds itself
  (`:333-339`).
- UI: rail in `templates/web/_partials/left_rail.html`; routes in
  `web/ui.py` (`_search_screen` `:394`, `docs_page` `:529` which today strips
  plans via `planstatus.without_plans`), `web/planui.py` (`/ui/plans…`
  `:114-118`). Documents' current `?filter=` is a substring match on
  id/title/tags, not search.
- Search entry points to extend together: `query.search` (`query.py:417`),
  `cli.py` `kb query` (`:2102`), `mcp.py` `kb_search` (`:148`), REST
  `/api/search` (`web/api.py:227`).

## 4. Decided by the owner

- One kind per repo, fixed by `kb init --kind`. Hub kind mapping as in §1.
- The registry is where the hub declares each repo's kind.
- Upgrade happens by re-running `kb init` on the hub; it must leave the
  federation showing correctly in the UI and in kind-filtered search.
- Menu set Overview · Document · Ticket · Code, Plans renamed Ticket,
  separate Search item removed (mockup approved).
- Per-menu search searches that kind only; top search searches all kinds,
  displayed as option A (mixed list, kind badges, kind chips).
- Agent filters per role as in Goal 8. No filter = all kinds.
- Code menu content = `-code` + `-svc` (with `hist.*`); no `docs/impl`
  publishing.

## 5. Calls made by the designer (owner may override)

- **Hub kind values are `kb | ba | dev`**, not the repo-config values;
  `hub` and `child` both map to `kb`.
- **No directory restructure.** Kind is recorded, not encoded in paths:
  moving leaves would break nested-hub paths, digest checks
  (`content_sha256`) and code-sync's manifest regex.
- **Kind is recorded in each leaf's `_meta.yaml`** (`kind:` optional, default
  inferred) and carried into the search DB per section. Registry kind wins on
  a governed hub; an ungoverned hub (empty registry) takes the publisher's
  config kind; legacy leaves without it are inferred from doc-id suffix.
- **Mismatch rejects the publish** with a message naming both kinds and the
  registry line to fix. Applies to both the intake route and the local
  snapshot route where the registry is consulted today.
- **Upgrade = `kb init --kind hub` re-run**: for each registry entry without
  `kind`, propose one from what that repo has published (suffix inference),
  print the proposed registry diff, and write it only after the operator
  confirms (interactive prompt; `--yes` for CI). Leaves are back-filled the
  same way. A registry entry that becomes `kind`-bearing switches to the
  mapping form `{repo_id, kind, workflow?}`.
- **Routes:** `/ui/tickets…` replaces `/ui/plans…`; old `/ui/plans…` URLs
  redirect (301) so existing links keep working. Code gets `/ui/code`; doc and
  section reader pages are shared by all three menus.
- **Per-menu search is real search** (`query.search` with a kind filter), not
  the current substring filter; results render inside the menu.
- **`kb doctor`** gains a hub check: registry entries without `kind`, and
  leaves whose recorded kind disagrees with the registry.

## 6. Left to the builder

- Exact field placement in models (`RegistryEntry.kind`, `_meta.yaml`,
  whether `FedIndexEntry` also carries it) within the compat rule.
- Search DB shape for kind (column on `sections` vs a join through repo) and
  the schema-version bump.
- Template/markup details of badges, chips and the per-menu search box,
  following the existing `style.css` and the approved mockup.
- Wording of skill-body changes, keeping each body's current structure.
- Test layout, following the repo's existing test conventions; changelog and
  version bump per repo convention.
