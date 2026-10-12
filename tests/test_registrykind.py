from pathlib import Path

import pytest
import yaml

from strata_kb import models, registrykind
from strata_kb.federation import RegistryError

COMMENTED = """\
# hub allowlist
repos:
  # owner: team-x
  acme/plain: plain-id   # trailing note
  # owner: team-y

  acme/pinned: {repo_id: pinned-id, workflow: ".github/workflows/pub.yml@refs/heads/main"}
  acme/block:
    repo_id: block-id
    workflow: w.yml  # keep me
  "acme/quoted": "quoted-id"
  acme/done: {repo_id: done-id, kind: dev}
# end
"""


def _kinds(text: str) -> dict[str, str]:
    reg = models.Registry.model_validate(yaml.safe_load(text))
    return {k: reg.resolve(k).kind for k in reg.repos}  # type: ignore[union-attr]


def test_apply_preserves_comments():
    out = registrykind.apply(
        COMMENTED,
        {
            "acme/plain": "kb",
            "acme/pinned": "ba",
            "acme/block": "dev",
            "acme/quoted": "kb",
        },
    )

    assert _kinds(out) == {
        "acme/plain": "kb",
        "acme/pinned": "ba",
        "acme/block": "dev",
        "acme/quoted": "kb",
        "acme/done": "dev",
    }
    new = out.splitlines()
    for line in COMMENTED.splitlines():
        if line.lstrip().startswith("#"):
            assert line in new
    assert "  acme/plain: {repo_id: plain-id, kind: kb}   # trailing note" in new
    assert '  "acme/quoted": {repo_id: "quoted-id", kind: kb}' in new
    assert "    workflow: w.yml  # keep me" in new
    assert new[new.index("    workflow: w.yml  # keep me") + 1] == "    kind: dev"


def test_apply_block_entry_at_eof_without_newline():
    out = registrykind.apply("repos:\n  a/b:\n    repo_id: x", {"a/b": "kb"})

    assert out == "repos:\n  a/b:\n    repo_id: x\n    kind: kb\n"


def test_apply_unknown_key_raises():
    with pytest.raises(ValueError, match="no entry"):
        registrykind.apply(COMMENTED, {"nope/x": "kb"})


def test_apply_invalid_kind_aborts():
    with pytest.raises(ValueError, match="does not parse"):
        registrykind.apply(COMMENTED, {"acme/plain": "bogus"})


def _leaf(fed: Path, path_id: str, doc_id: str, title: str = "T", tags=()) -> None:
    d = fed / path_id
    d.mkdir(parents=True)
    (d / "_meta.yaml").write_text(
        f"repo_id: {path_id.rsplit('/', 1)[-1]}\nsource_commit: abc\n", encoding="utf-8"
    )
    (d / "index.yaml").write_text(
        yaml.safe_dump({"docs": [{"id": doc_id, "title": title, "tags": list(tags)}]}),
        encoding="utf-8",
    )


def test_propose_from_published(tmp_path: Path):
    fed = tmp_path / "federation"
    _leaf(fed, "x", "svc-code", tags=["code", "curated"])
    _leaf(fed, "p", "m1", "Mission — plan", ["plan", "generated"])
    _leaf(fed, "k", "guide")
    _leaf(fed, "mid/inner", "guide")
    _leaf(fed, "allba/a", "m1", "Mission — plan", ["plan", "generated"])
    _leaf(fed, "allba/b", "m2", "Mission — plan", ["plan", "generated"])
    _leaf(fed, "mixed/a", "guide")
    _leaf(fed, "mixed/b", "svc-code", tags=["code", "curated"])
    (fed / "registry.yaml").write_text(
        "repos:\n"
        "  o/x: x\n  o/p: p\n  o/k: k\n  o/mid: mid\n  o/gone: gone\n"
        "  o/up: ../up\n  o/allba: allba\n  o/mixed: mixed\n"
        '  o/dot: "."\n  o/blank: ""\n'
        "  o/pinned: {repo_id: k, kind: dev}\n",
        encoding="utf-8",
    )

    assert registrykind.propose(fed) == {
        "o/x": "dev",
        "o/p": "ba",
        "o/k": "kb",
        "o/mid": "kb",
        "o/gone": "",
        "o/up": "",
        "o/allba": "kb",
        "o/mixed": "kb",
        "o/dot": "",
        "o/blank": "",
    }


def test_apply_fills_explicit_empty_kind_in_place():
    text = (
        "repos:\n"
        '  a/flow: {repo_id: f, kind: ""}\n'
        "  a/block:\n"
        "    repo_id: b\n"
        "    kind: ''\n"
        "    workflow: w.yml\n"
    )

    out = registrykind.apply(text, {"a/flow": "dev", "a/block": "ba"})

    assert out == (
        "repos:\n"
        "  a/flow: {repo_id: f, kind: dev}\n"
        "  a/block:\n"
        "    repo_id: b\n"
        "    kind: ba\n"
        "    workflow: w.yml\n"
    )


def test_propose_bad_registry_raises(tmp_path: Path):
    fed = tmp_path / "federation"
    fed.mkdir()
    (fed / "registry.yaml").write_text("repos: [oops\n", encoding="utf-8")

    with pytest.raises(RegistryError):
        registrykind.propose(fed)
