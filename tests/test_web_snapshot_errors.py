"""M8: a corrupt federation manifest took the doc routes down with a 500."""

# fed_hub (conftest.py's make_fed_entry calls) pins these doc_id -> section_id
# pairs -- whichever manifest _corrupt_a_manifest's rglob() picks, this maps
# the returned doc_id to the one section it holds, for the section-route tests.
SECTION_FOR_DOC = {"icao-annex-2": "1.1", "arinc-424": "5.3"}


def _corrupt_a_manifest(hub_dir):
    manifest = next((hub_dir / "federation").rglob("_manifest.yaml"))
    manifest.write_text("id: [unclosed\n", encoding="utf-8", newline="\n")
    return manifest.parent.name


def _make_manifest_schema_invalid(hub_dir):
    """Valid YAML, invalid against the Manifest schema (sections must be a
    list) -- exercises the ValidationError arm, distinct from the YAMLError
    arm _corrupt_a_manifest exercises."""
    manifest = next((hub_dir / "federation").rglob("_manifest.yaml"))
    manifest.write_text(
        "id: ok\ntitle: t\nrevision: r\nsections: notalist\n",
        encoding="utf-8", newline="\n",
    )
    return manifest.parent.name


def test_api_doc_detail_is_503_json_not_500(web_client_logged_in, hub_dir):
    doc_id = _corrupt_a_manifest(hub_dir)
    resp = web_client_logged_in.get(f"/api/docs/{doc_id}")
    assert resp.status_code == 503
    assert resp.json()["error"] == "snapshot_corrupt"
    assert resp.headers["x-content-type-options"] == "nosniff"  # SecurityHeadersMiddleware still applies


def test_ui_doc_page_renders_the_shell_not_a_bare_500(web_client_logged_in, hub_dir):
    doc_id = _corrupt_a_manifest(hub_dir)
    resp = web_client_logged_in.get(f"/ui/docs/{doc_id}")
    assert resp.status_code == 503
    assert "Internal Server Error" not in resp.text
    assert "Strata" in resp.text  # the shell rendered


def test_ui_home_still_degrades_to_200(web_client_logged_in, hub_dir):
    _corrupt_a_manifest(hub_dir)
    assert web_client_logged_in.get("/ui").status_code == 200


def test_api_section_is_503_json_not_500(web_client_logged_in, hub_dir):
    doc_id = _corrupt_a_manifest(hub_dir)
    section_id = SECTION_FOR_DOC[doc_id]
    resp = web_client_logged_in.get(f"/api/docs/{doc_id}/sections/{section_id}")
    assert resp.status_code == 503
    assert resp.json()["error"] == "snapshot_corrupt"


def test_ui_section_page_is_503_not_a_bare_500(web_client_logged_in, hub_dir):
    doc_id = _corrupt_a_manifest(hub_dir)
    section_id = SECTION_FOR_DOC[doc_id]
    resp = web_client_logged_in.get(f"/ui/docs/{doc_id}/{section_id}")
    assert resp.status_code == 503
    assert "Internal Server Error" not in resp.text
    assert "Strata" in resp.text  # the shell rendered


def test_api_doc_detail_validation_error_manifest_is_503(web_client_logged_in, hub_dir):
    doc_id = _make_manifest_schema_invalid(hub_dir)
    resp = web_client_logged_in.get(f"/api/docs/{doc_id}")
    assert resp.status_code == 503
    assert resp.json()["error"] == "snapshot_corrupt"


def test_api_section_validation_error_manifest_is_503(web_client_logged_in, hub_dir):
    doc_id = _make_manifest_schema_invalid(hub_dir)
    section_id = SECTION_FOR_DOC[doc_id]
    resp = web_client_logged_in.get(f"/api/docs/{doc_id}/sections/{section_id}")
    assert resp.status_code == 503
    assert resp.json()["error"] == "snapshot_corrupt"


def test_ui_section_page_validation_error_manifest_is_503(web_client_logged_in, hub_dir):
    doc_id = _make_manifest_schema_invalid(hub_dir)
    section_id = SECTION_FOR_DOC[doc_id]
    resp = web_client_logged_in.get(f"/ui/docs/{doc_id}/{section_id}")
    assert resp.status_code == 503
    assert "Internal Server Error" not in resp.text
    assert "Strata" in resp.text  # the shell rendered


def test_api_search_is_503_json_not_500(web_client_logged_in, hub_dir):
    _corrupt_a_manifest(hub_dir)
    resp = web_client_logged_in.get("/api/search?q=airspace")
    assert resp.status_code == 503
    assert resp.json()["error"] == "snapshot_corrupt"


def test_ui_search_screen_renders_shell_not_a_bare_500(web_client_logged_in, hub_dir):
    _corrupt_a_manifest(hub_dir)
    resp = web_client_logged_in.get("/ui?q=airspace")
    assert resp.status_code == 503
    assert "Internal Server Error" not in resp.text
    assert "Strata" in resp.text  # the shell rendered
