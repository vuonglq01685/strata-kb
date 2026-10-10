"""2026-10-10 review §6.2 F1: manifests were parsed with pure-Python YAML on
every call, several times per web request. `models.load_yaml_data` parses
with libyaml and caches by stat; a file younger than the racy window is
always re-parsed."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
import yaml

from strata_kb import models


@pytest.fixture(autouse=True)
def _fresh_cache():
    models.clear_yaml_cache()
    yield
    models.clear_yaml_cache()


@pytest.fixture
def parses(monkeypatch):
    calls: list[str] = []
    real = yaml.load

    def counting(stream, Loader):
        calls.append("parse")
        return real(stream, Loader=Loader)

    monkeypatch.setattr(models.yaml, "load", counting)
    return calls


def _age(path: Path, seconds: float = 10.0) -> None:
    past = time.time() - seconds
    os.utime(path, (past, past))


def _manifest(path: Path, title: str = "Doc", n: int = 3) -> Path:
    models.save_yaml_model(
        path,
        models.Manifest(
            id="d",
            title=title,
            sections=[
                models.SectionEntry(id=f"{i}", title=f"S{i}", file="ch1")
                for i in range(n)
            ],
        ),
    )
    return path


def test_an_old_file_is_parsed_once(tmp_path, parses):
    path = _manifest(tmp_path / "_manifest.yaml")
    _age(path)
    a = models.load_yaml_model(path, models.Manifest)
    b = models.load_yaml_model(path, models.Manifest)
    assert parses == ["parse"]
    assert a == b and a is not b


def test_a_fresh_file_is_parsed_every_time(tmp_path, parses):
    path = _manifest(tmp_path / "_manifest.yaml")
    models.load_yaml_model(path, models.Manifest)
    models.load_yaml_model(path, models.Manifest)
    assert parses == ["parse", "parse"]


def test_a_rewrite_is_seen_even_with_the_same_size(tmp_path):
    path = _manifest(tmp_path / "_manifest.yaml", title="Aaaa")
    _age(path, 20)
    assert models.load_yaml_model(path, models.Manifest).title == "Aaaa"
    _manifest(path, title="Bbbb")  # same byte length
    _age(path, 10)  # still older than the racy window, but a different stat
    assert models.load_yaml_model(path, models.Manifest).title == "Bbbb"


def test_mutating_a_returned_model_never_reaches_the_next_call(tmp_path):
    path = _manifest(tmp_path / "_manifest.yaml")
    _age(path)
    first = models.load_yaml_model(path, models.Manifest)
    first.sections.clear()
    first.title = "changed"
    again = models.load_yaml_model(path, models.Manifest)
    assert again.title == "Doc"
    assert len(again.sections) == 3


def test_the_cache_is_bounded(tmp_path, monkeypatch, parses):
    monkeypatch.setattr(models, "_YAML_CACHE_MAX", 2)
    paths = []
    for i in range(3):
        p = _manifest(tmp_path / f"m{i}.yaml")
        _age(p)
        paths.append(p)
    for p in paths:
        models.load_yaml_model(p, models.Manifest)
    assert len(models._yaml_cache) == 2
    models.load_yaml_model(paths[0], models.Manifest)  # evicted → parsed again
    assert len(parses) == 4


def test_a_missing_file_still_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        models.load_yaml_model(tmp_path / "nope.yaml", models.Manifest)


def test_malformed_yaml_raises_and_is_not_cached(tmp_path, parses):
    path = tmp_path / "bad.yaml"
    path.write_text("id: [unclosed\n", encoding="utf-8")
    _age(path)
    for _ in range(2):
        with pytest.raises(yaml.YAMLError):
            models.load_yaml_model(path, models.Manifest)
    assert parses == ["parse", "parse"]


def _yaml_files() -> list[Path]:
    root = Path(__file__).resolve().parent.parent
    found = [
        *root.glob("tests/fixtures/**/*.yaml"),
        *root.glob("src/strata_kb/templates/**/*.yaml"),
        *root.glob("src/strata_kb/templates/**/*.yml"),
    ]
    return sorted(found)


@pytest.mark.parametrize("path", _yaml_files(), ids=lambda p: p.name)
def test_libyaml_and_pure_python_parse_identically(path):
    text = path.read_text(encoding="utf-8")
    try:
        expected = yaml.load(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError:
        pytest.skip("template is not plain YAML before rendering")
    assert yaml.load(text, Loader=models._YamlLoader) == expected  # noqa: S506 -- CSafeLoader/SafeLoader


def test_the_fast_loader_is_libyaml_when_available():
    if yaml.__with_libyaml__:
        assert models._YamlLoader is yaml.CSafeLoader
