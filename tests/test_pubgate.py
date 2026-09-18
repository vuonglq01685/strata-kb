import pytest

from center_kb import pubgate


@pytest.mark.parametrize("rid", ["repo-alpha", "a", "a.b", "a_b", "A1", "kb-hub"])
def test_valid_repo_ids_pass_through(rid):
    assert pubgate.normalize_repo_id(rid) == rid


@pytest.mark.parametrize(
    "rid",
    ["", ".", "..", "../evil", "a/b", "a\\b", "C:evil", "évil", " victim", "victim "],
)
def test_invalid_shapes_are_refused(rid):
    with pytest.raises(pubgate.GateError):
        pubgate.normalize_repo_id(rid)


def test_over_long_repo_id_is_refused():
    with pytest.raises(pubgate.GateError, match="the limit is 64"):
        pubgate.normalize_repo_id("x" * 300)


@pytest.mark.parametrize("rid", ["victim.", "victim.."])
def test_trailing_dot_is_refused(rid):
    with pytest.raises(pubgate.GateError, match="ends with a dot"):
        pubgate.normalize_repo_id(rid)


@pytest.mark.parametrize(
    "rid",
    [
        "CON", "con", "NUL", "COM1", "lpt9", "CON.md",
        # Round 3 (MEDIUM-2): these used to be accepted here while
        # intake.py's member-name rule already refused them as tar
        # members -- both COM0/LPT0 and the '$' console-handle names are
        # now part of the one shared pubgate.WIN32_DEVICES set. 'CONIN$'
        # itself never reaches this check (REPO_ID_RE refuses '$' first),
        # so only the plain-ASCII COM0/LPT0 spellings are meaningfully new
        # here.
        "COM0", "LPT0", "lpt0",
    ],
)
def test_reserved_windows_device_names_are_refused(rid):
    with pytest.raises(pubgate.GateError, match="reserved Windows device name"):
        pubgate.normalize_repo_id(rid)


@pytest.mark.parametrize(
    "stem",
    ["CON", "con", "Con", "NUL", "COM1", "lpt9", "COM0", "LPT0", "CONIN$", "CONOUT$"],
)
def test_is_reserved_device_name_matches_the_shared_set(stem):
    assert pubgate.is_reserved_device_name(stem)


def test_is_reserved_device_name_strips_a_trailing_space_before_matching():
    """round-4 (P30): repo-ids can never carry a space (REPO_ID_RE has no
    space in its character class), so normalize_repo_id's own tests above
    can never exercise this -- intake.py's member-name rule is the one
    real caller that needs it ('NUL .txt', which Windows treats as the
    NUL device). Pinned directly on the shared predicate so it is not
    only reachable through a harder-to-construct tar member fixture."""
    assert pubgate.is_reserved_device_name("NUL ")
    assert pubgate.is_reserved_device_name("nul  ")  # multiple trailing spaces


def test_is_reserved_device_name_control_ordinary_stem_is_not_reserved():
    """No-op control: an ordinary stem that merely LOOKS similar must not
    match -- proves the two tests above are not vacuously true from an
    over-broad predicate (e.g. one that matched any 2-3 letter stem)."""
    assert not pubgate.is_reserved_device_name("CONFIG")
    assert not pubgate.is_reserved_device_name("console")
    assert not pubgate.is_reserved_device_name("doc-a")


def test_case_insensitive_collision_with_a_sibling_is_refused():
    with pytest.raises(pubgate.GateError, match="collides with the existing entry 'victim'"):
        pubgate.normalize_repo_id("VICTIM", existing=["victim", "other"])


def test_republishing_the_same_entry_is_not_a_collision():
    assert pubgate.normalize_repo_id("victim", existing=["victim"]) == "victim"


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/org/repo.git", "org/repo"),
        ("https://github.com/org/repo", "org/repo"),
        ("https://x-access-token:ghs_SECRET@github.com/org/repo.git", "org/repo"),
        ("git@github.com:org/repo.git", "org/repo"),
        ("ssh://git@github.com/org/repo.git", "org/repo"),
        ("https://gitlab.com/group/sub/repo.git", "group/sub/repo"),
        ("https://github.com/org/repo.git/", "org/repo"),
    ],
)
def test_owner_repo_parsed_from_remote(url, expected):
    assert pubgate.owner_repo_from_remote(url) == expected


@pytest.mark.parametrize("url", ["", "/srv/kb-hub", "C:\\hubs\\kb-hub", "https://github.com/org"])
def test_local_paths_and_incomplete_urls_have_no_owner_repo(url):
    assert pubgate.owner_repo_from_remote(url) is None


REG = {"org/victim": "victim", "Org/Attacker": "attacker"}


def test_registry_maps_the_publisher_to_its_own_repo_id():
    rid = pubgate.resolve_identity(REG, "git@github.com:org/victim.git", None, "hub")
    assert rid == "victim"


def test_registry_lookup_is_case_insensitive():
    rid = pubgate.resolve_identity(REG, "https://github.com/ORG/Attacker.git", None, "hub")
    assert rid == "attacker"


def test_requesting_another_repos_id_is_refused():
    with pytest.raises(pubgate.GateError, match="maps 'org/attacker' to repo-id 'attacker'"):
        pubgate.resolve_identity(
            REG, "https://github.com/org/attacker.git", "victim", "hub"
        )


def test_repo_id_mismatch_names_both_the_flag_and_the_config_entry():
    """P64: the same refusal fires when the trigger was `repo_id:` in
    .kb/config.yaml (cli.py passes effective_repo_id(), the flag OR the
    config value) -- so the message must not tell the operator to drop a
    flag they never passed. Fails against the old text ('drop --repo-id,
    or ask the hub owner')."""
    with pytest.raises(
        pubgate.GateError, match=r"drop --repo-id or the repo_id: entry in \.kb/config\.yaml"
    ):
        pubgate.resolve_identity(
            REG, "https://github.com/org/attacker.git", "victim", "hub"
        )


def test_unregistered_publisher_is_refused_with_the_registry_hint():
    with pytest.raises(pubgate.GateError, match="is not registered on hub"):
        pubgate.resolve_identity(REG, "https://github.com/org/stranger.git", None, "hub")


def test_publisher_without_a_remote_is_told_to_add_one():
    """P64: `kb ci-publish` is GitHub-only at both ends (intake.py pushes to
    a hardcoded github.com URL; ghapp.repo_full_from_url raises on a
    non-GitHub URL) and a repo with no git remote cannot even be running in
    that flow, so this refusal must not name it. Fails against the old text
    ('publish through `kb ci-publish`')."""
    with pytest.raises(pubgate.GateError) as exc:
        pubgate.resolve_identity(REG, "", None, "hub")
    assert "ci-publish" not in str(exc.value)
    assert "add a git remote" in str(exc.value)
    assert "remove the registry" in str(exc.value)


def test_matching_requested_repo_id_is_accepted():
    rid = pubgate.resolve_identity(REG, "https://github.com/org/victim", "victim", "hub")
    assert rid == "victim"


@pytest.mark.parametrize(
    "explicit,has_remote,can_pr,governed,expected",
    [
        ("direct", False, False, False, "direct"),
        ("direct", True, True, False, "direct"),
        ("direct", False, False, True, "direct"),   # local-path governed hub
        ("pr", True, True, False, "pr"),
        ("auto", False, False, False, "direct"),    # README's stated kb publish mode behaviour (§7.9)
        ("auto", False, False, True, "direct"),
        ("auto", True, True, False, "pr"),
        ("auto", True, True, True, "pr"),
    ],
)
def test_mode_table_accepted_rows(explicit, has_remote, can_pr, governed, expected):
    assert (
        pubgate.decide_mode(explicit, has_remote, can_pr, governed, "hub") == expected
    )


def test_governed_remote_hub_refuses_direct():
    with pytest.raises(pubgate.GateError, match="takes contributions by PR"):
        pubgate.decide_mode("direct", True, True, True, "hub")


def test_governed_remote_hub_direct_refusal_names_the_always_available_lever():
    """P64: this refusal must not just assert `kb ci-publish` works -- it
    needs GitHub on both ends, so the message must name that requirement
    plus the one lever that always exists (un-governing the hub). Fails
    against the old text ('or through `kb ci-publish`, not by direct
    push' with no fallback lever named)."""
    with pytest.raises(pubgate.GateError) as exc:
        pubgate.decide_mode("direct", True, True, True, "hub")
    message = str(exc.value)
    assert "needs GitHub on both the publisher and the hub" in message
    assert "remove federation/registry.yaml" in message


def test_pr_without_a_remote_is_refused():
    with pytest.raises(pubgate.GateError, match="has no git remote"):
        pubgate.decide_mode("pr", False, False, False, "hub")


@pytest.mark.parametrize("explicit", ["pr", "auto"])
def test_remote_hub_that_cannot_open_a_pr_is_refused_with_two_exits(explicit):
    with pytest.raises(pubgate.GateError) as exc:
        pubgate.decide_mode(explicit, True, False, False, "hub")
    assert "--pr" in str(exc.value)
    assert "--direct" in str(exc.value)


@pytest.mark.parametrize("explicit", ["pr", "auto"])
def test_governed_remote_hub_that_cannot_open_a_pr_is_pointed_at_ci_publish(explicit):
    with pytest.raises(pubgate.GateError) as exc:
        pubgate.decide_mode(explicit, True, False, True, "hub")
    assert "ci-publish" in str(exc.value)
    assert "--direct" not in str(exc.value)


@pytest.mark.parametrize("explicit", ["pr", "auto"])
def test_governed_no_pr_message_states_the_requirement_not_an_assertion(explicit):
    """P64: measured live on a governed non-GitHub hub, this refusal used
    to unconditionally name `kb ci-publish` as if it always worked. It must
    instead say what that route requires (GitHub at both ends), name
    GH_HOST for GitHub Enterprise, and name the lever that always exists.
    Fails against the old text ('either fix that and re-run with --pr, or
    publish through `kb ci-publish`', with no GH_HOST or registry-removal
    mention)."""
    with pytest.raises(pubgate.GateError) as exc:
        pubgate.decide_mode(explicit, True, False, True, "hub")
    message = str(exc.value)
    assert "GH_HOST" in message
    assert "needs GitHub on both the publisher and the hub" in message
    assert "remove federation/registry.yaml" in message


@pytest.mark.parametrize(
    "rel",
    [
        "index.yaml",
        "demo-doc/_manifest.yaml",
        "demo-doc/ch1.md",
        "demo-doc/ch1.raw.md",
        "demo-doc/assets/" + "a" * 64 + ".png",
        # one and two levels deeper: a federation/ source, nested tiers included
        "child/index.yaml",
        "child/_meta.yaml",
        "mid/deep/demo-doc/ch1.md",
        "mid/deep/demo-doc/assets/" + "b" * 64 + ".webp",
    ],
)
def test_kb_artifacts_are_kept(rel):
    assert pubgate.is_kb_artifact(rel) is True


@pytest.mark.parametrize(
    "rel",
    [
        "config.yaml",
        ".env",
        ".gitkeep",
        "demo-doc/ch1.md.bak",
        "demo-doc/notes.txt",
        "demo-doc/.hidden/ch1.md",
        "_assets.yaml",
        "child/_assets.yaml",
        "demo-doc/assets/nested/x.png",
        "/etc/passwd.md",
        "/index.yaml",
        "a\\..\\..\\evil.md",
        "demo-doc\\ch1.md",
        "..\\evil.md",
    ],
)
def test_everything_else_is_skipped(rel):
    assert pubgate.is_kb_artifact(rel) is False


def test_split_allowlist_reports_what_it_dropped():
    manifest = {
        "index.yaml": "a",
        "config.yaml": "b",
        ".env": "c",
        "demo-doc/ch1.md": "d",
    }
    kept, skipped = pubgate.split_allowlist(manifest)
    assert kept == {"index.yaml": "a", "demo-doc/ch1.md": "d"}
    assert skipped == [".env", "config.yaml"]


def test_asset_record_basename_stays_in_sync_with_assetstore():
    """Wave F fix round 1's report claimed `_ASSET_RECORD_BASENAME` is "kept
    in sync by tests/test_pubgate.py" -- re-review M1 measured that no
    assertion anywhere actually tied it to `assetstore.RECORD_NAME` (a grep
    for the name matched only pubgate.py itself). This is the one-line fix:
    pin the sync guarantee the comment at pubgate.py already promises, so the
    two names drifting apart fails here instead of silently reopening the
    `_assets.yaml` predicate mismatch item 1 exists to close."""
    from center_kb import assetstore

    assert pubgate._ASSET_RECORD_BASENAME == assetstore.RECORD_NAME
