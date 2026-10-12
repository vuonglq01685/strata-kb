from __future__ import annotations

import pytest

from strata_kb import kinds, models, planingest, planstatus
from strata_kb.kinds import KindMismatchError, UnknownKindError


def _doc(doc_id: str, title: str = "", tags: list[str] | None = None):
    return models.IndexEntry(id=doc_id, title=title or doc_id, tags=tags or [])


def test_hub_kind_maps_config_kinds():
    assert kinds.hub_kind("hub") == "kb"
    assert kinds.hub_kind("child") == "kb"
    assert kinds.hub_kind("ba") == "ba"
    assert kinds.hub_kind("dev") == "dev"
    with pytest.raises(UnknownKindError):
        kinds.hub_kind("")
    with pytest.raises(UnknownKindError):
        kinds.hub_kind("x")


def test_normalize_kinds():
    assert kinds.normalize_kinds([" Dev", "kb", "dev"]) == ["dev", "kb"]
    assert kinds.normalize_kinds(None) == []
    assert kinds.normalize_kinds([]) == []
    with pytest.raises(UnknownKindError):
        kinds.normalize_kinds(["code"])


def test_infer_kind():
    plan = _doc("ba-one", f"ba-one {planingest.TITLE_SUFFIX}", ["plan", "generated"])
    assert kinds.infer_kind([plan]) == "ba"
    assert kinds.infer_kind([_doc("x-code")]) == "dev"
    assert kinds.infer_kind([_doc("x-svc")]) == "dev"
    assert kinds.infer_kind([_doc("release-plan")]) == "kb"
    assert kinds.infer_kind([]) == "kb"


def test_plan_marker_is_single_sourced():
    assert kinds.PLAN_TITLE_SUFFIX == planingest.TITLE_SUFFIX
    assert planstatus.is_plan is kinds.is_plan


def test_check_publish_kind():
    assert kinds.check_publish_kind("", "") == ""
    assert kinds.check_publish_kind("dev", "") == "dev"
    assert kinds.check_publish_kind("", "ba") == "ba"
    assert kinds.check_publish_kind("kb", "kb") == "kb"
    with pytest.raises(KindMismatchError) as exc:
        kinds.check_publish_kind("ba", "dev")
    assert (exc.value.registry_kind, exc.value.repo_kind) == ("ba", "dev")


def test_unknown_kind_error_is_not_value_error():
    assert not issubclass(UnknownKindError, ValueError)
