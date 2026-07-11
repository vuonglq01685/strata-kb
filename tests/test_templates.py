from importlib import resources

from aero_kb.initcmd import TEMPLATE_MAP

WEB_TEMPLATES = [
    "base.html", "login.html", "search.html",
    "docs.html", "doc.html", "section.html", "style.css",
]


def test_all_web_templates_exist_as_package_resources():
    base = resources.files("aero_kb").joinpath("templates/web")
    for name in WEB_TEMPLATES:
        assert base.joinpath(name).is_file(), name


def test_all_init_templates_exist_as_package_resources():
    base = resources.files("aero_kb").joinpath("templates/init")
    for resource_name in TEMPLATE_MAP.values():
        assert base.joinpath(resource_name).is_file(), resource_name
