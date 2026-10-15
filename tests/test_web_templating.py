from strata_kb.web import templating


def test_render_escapes_by_default():
    env = templating.make_env()
    tmpl = env.from_string("<p>{{ value }}</p>")
    assert tmpl.render(value="<script>x</script>") == (
        "<p>&lt;script&gt;x&lt;/script&gt;</p>"
    )


def test_render_reads_from_package():
    out = templating.render("login.html", error="UNIQUE_ERROR_MARKER_XYZ")
    assert "UNIQUE_ERROR_MARKER_XYZ" in out


def test_static_urls_carry_the_version_so_an_upgrade_busts_the_cache():
    # /ui/static/* is served with max-age=86400: an unversioned URL keeps
    # the old stylesheet for a day after a hub upgrade.
    import strata_kb

    v = f"?v={strata_kb.__version__}"
    for name in ("login.html", "setup.html"):
        assert f'href="/ui/static/style.css{v}"' in templating.render(name)
    assert templating.make_env().globals["asset_v"] == strata_kb.__version__
    base = templating.make_env().loader.get_source(templating.make_env(), "base.html")[
        0
    ]
    assert 'href="/ui/static/style.css?v={{ asset_v }}"' in base
    assert 'src="/ui/static/app.js?v={{ asset_v }}"' in base
