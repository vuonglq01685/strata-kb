from __future__ import annotations

import pytest

from strata_kb import federation


def test_missing_file_returns_empty(tmp_path):
    reg = federation.load_registry(tmp_path)
    assert reg.repos == {}


def test_loads_mapping(tmp_path):
    (tmp_path / "registry.yaml").write_text(
        "repos:\n  acme/flight-docs: flight-docs\n", encoding="utf-8"
    )
    reg = federation.load_registry(tmp_path)
    assert reg.repos["acme/flight-docs"] == "flight-docs"


@pytest.mark.parametrize("bad", ["repos: [broken", "repos: 42"])
def test_invalid_yaml_or_schema_raises(tmp_path, bad):
    (tmp_path / "registry.yaml").write_text(bad, encoding="utf-8")
    with pytest.raises(federation.RegistryError):
        federation.load_registry(tmp_path)


def test_registry_accepts_the_plain_string_form(tmp_path):
    import yaml

    fed = tmp_path
    (fed / "registry.yaml").write_text(
        yaml.safe_dump({"repos": {"org/repo": "rid"}}), encoding="utf-8", newline="\n"
    )
    reg = federation.load_registry(fed)
    assert reg.resolve("org/repo").repo_id == "rid"
    assert reg.resolve("org/repo").workflow == ""
    assert federation.registry_map(reg) == {"org/repo": "rid"}


def test_registry_accepts_the_mapping_form_with_a_workflow_pin(tmp_path):
    import yaml

    fed = tmp_path
    (fed / "registry.yaml").write_text(
        yaml.safe_dump(
            {
                "repos": {
                    "org/repo": {
                        "repo_id": "rid",
                        "workflow": "org/repo/.github/workflows/kb-publish.yml@refs/heads/main",
                    }
                }
            }
        ),
        encoding="utf-8",
        newline="\n",
    )
    reg = federation.load_registry(fed)
    assert reg.resolve("org/repo").repo_id == "rid"
    assert reg.resolve("org/repo").workflow.endswith("@refs/heads/main")
    assert federation.registry_map(reg) == {"org/repo": "rid"}


def test_registry_resolve_returns_none_for_unregistered_repo(tmp_path):
    reg = federation.load_registry(tmp_path)
    assert reg.resolve("nobody/nothing") is None


def test_a_typo_d_workflow_key_is_rejected_not_silently_dropped(tmp_path):
    """I-3: RegistryEntry had no `extra="forbid"`, so a typo'd
    `workflw:` (missing the 'o') validated cleanly and silently dropped the
    pin the hub owner thought they set -- authorize() would then accept
    ANY workflow for that repo-id. This is the actual authentication
    boundary (see Registry's docstring); it must fail closed on an
    operator typo, not just on a malicious payload."""
    (tmp_path / "registry.yaml").write_text(
        "repos:\n"
        "  org/repo:\n"
        "    repo_id: rid\n"
        "    workflw: org/repo/.github/workflows/kb-publish.yml@refs/heads/main\n",
        encoding="utf-8",
    )
    with pytest.raises(federation.RegistryError):
        federation.load_registry(tmp_path)


def test_a_stray_top_level_key_in_the_registry_is_rejected_not_silently_dropped(
    tmp_path,
):
    """N-8: `Registry` itself (not just `RegistryEntry`) carries
    `extra="forbid"`, but nothing exercised it -- a mutant dropping just
    that model_config survived the whole suite. A typo'd top-level key
    (e.g. 'repo:' for 'repos:') must fail closed the same way a typo'd
    per-entry key does (see test_a_typo_d_workflow_key_is_rejected_not_
    silently_dropped above), not silently validate as an empty registry."""
    (tmp_path / "registry.yaml").write_text(
        "repos:\n  org/repo: rid\nbogus_top_level_key: true\n", encoding="utf-8"
    )
    with pytest.raises(federation.RegistryError):
        federation.load_registry(tmp_path)


def test_case_colliding_registry_keys_are_rejected(tmp_path):
    """Two entries differing only in case both load as distinct dict keys --
    a case-insensitive lookup elsewhere would silently pick whichever
    iterates last. On a governed hub that decides which repo-id a publisher
    may claim, so a near-duplicate key must fail closed, not resolve."""
    (tmp_path / "registry.yaml").write_text(
        "repos:\n  Org/Repo: rid-a\n  org/repo: rid-b\n", encoding="utf-8"
    )
    with pytest.raises(federation.RegistryError) as exc:
        federation.load_registry(tmp_path)
    assert "Org/Repo" in str(exc.value)
    assert "org/repo" in str(exc.value)
