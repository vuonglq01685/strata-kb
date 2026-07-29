import pytest

from center_kb.web import templating


def test_render_escapes_by_default(tmp_path):
    env = templating.make_env()
    tmpl = env.from_string("<p>{{ value }}</p>")
    assert tmpl.render(value="<script>x</script>") == (
        "<p>&lt;script&gt;x&lt;/script&gt;</p>"
    )


@pytest.mark.xfail(
    reason="login.html becomes a Jinja template in Task 4", strict=True
)
def test_render_reads_from_package():
    # login.html is still a string.Template file ($error, not {{ error }}),
    # so the Jinja env renders it as inert literal text and never
    # interpolates the value we pass in — this must fail until Task 4
    # rewrites login.html for Jinja.
    out = templating.render("login.html", error="UNIQUE_ERROR_MARKER_XYZ")
    assert "UNIQUE_ERROR_MARKER_XYZ" in out
