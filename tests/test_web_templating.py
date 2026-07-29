from center_kb.web import templating


def test_render_escapes_by_default():
    env = templating.make_env()
    tmpl = env.from_string("<p>{{ value }}</p>")
    assert tmpl.render(value="<script>x</script>") == (
        "<p>&lt;script&gt;x&lt;/script&gt;</p>"
    )


def test_render_reads_from_package():
    out = templating.render("login.html", error="UNIQUE_ERROR_MARKER_XYZ")
    assert "UNIQUE_ERROR_MARKER_XYZ" in out
