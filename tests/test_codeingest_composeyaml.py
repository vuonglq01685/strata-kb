from pathlib import Path

import pytest
import yaml

from strata_kb.codeingest import core
from strata_kb.codeingest.extractors import integrations as int_ext
from strata_kb.codeingest.extractors import services as svc_ext
from strata_kb.codeingest.extractors._composeyaml import load_compose


def _opts(root: Path) -> core.CodeIngestOptions:
    return core.CodeIngestOptions(
        repo_root=root, kb_dir=root / ".kb", doc_id="demo-code", repo_id="demo"
    )


_COMPOSE = (
    "services:\n"
    "  api:\n"
    "    image: api:1\n"
    "    ports: !reset []\n"
    "    environment:\n"
    "      REDIS_URL: redis://cache:6379\n"
    "  worker:\n"
    "    image: worker:1\n"
    "    environment: !override\n"
    "      QUEUE_URL: amqp://mq\n"
)


def test_reset_yields_the_empty_value_of_its_node_kind():
    assert load_compose("a: !reset\nb: !reset []\nc: !reset {}\n") == {
        "a": None, "b": [], "c": {},
    }


def test_override_yields_the_plain_value():
    data = load_compose(
        "ports: !override\n  - '8080:80'\nenv: !override\n  K: v\nn: !override 3\n"
        'q: !override "3"\nver: !override "1.10"\n'
    )
    # A quoted scalar under !override must stay a string (`yaml.safe_load`'s
    # own behaviour for `"3"` / `"1.10"`) -- unlike the unquoted `!override 3`
    # above, which resolves to the int 3.
    assert data == {
        "ports": ["8080:80"], "env": {"K": "v"}, "n": 3,
        "q": "3", "ver": "1.10",
    }


def test_other_tags_still_fail_like_safe_load():
    with pytest.raises(yaml.YAMLError):
        load_compose("x: !!python/object/apply:os.system ['ls']\n")


def test_services_reads_a_compose_file_that_uses_reset(tmp_path):
    (tmp_path / "docker-compose.yml").write_text(_COMPOSE, encoding="utf-8")
    result = svc_ext.ServicesExtractor().extract(tmp_path, _opts(tmp_path))
    assert not any("docker-compose.yml" in w for w in result.warnings), result.warnings
    assert {"svc.api", "svc.worker"} <= {s.id for s in result.sections}


def test_services_k8s_scan_ignores_a_nested_compose_file(tmp_path):
    # MyFlix field case: a compose file nested under a subdirectory (not at
    # repo root, so `_read_compose` never sees it) must still not surface a
    # warning from `_read_k8s`'s separate, repo-wide `*.y*ml` walk.
    nested = tmp_path / "infra" / "compose"
    nested.mkdir(parents=True)
    (nested / "docker-compose.cpu.yml").write_text(_COMPOSE, encoding="utf-8")
    result = svc_ext.ServicesExtractor().extract(tmp_path, _opts(tmp_path))
    assert not any("docker-compose.cpu.yml" in w for w in result.warnings), result.warnings


def test_integrations_reads_a_nested_compose_file_that_uses_reset(tmp_path):
    nested = tmp_path / "infra" / "compose"
    nested.mkdir(parents=True)
    (nested / "docker-compose.cpu.yml").write_text(_COMPOSE, encoding="utf-8")
    result = int_ext.IntegrationsExtractor().extract(tmp_path, _opts(tmp_path))
    assert not any("docker-compose.cpu.yml" in w for w in result.warnings), result.warnings
    assert "REDIS_URL" in "".join(s.l2_md + s.l3_md for s in result.sections)
