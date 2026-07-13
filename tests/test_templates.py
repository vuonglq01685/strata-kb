from importlib import resources

from center_kb.initcmd import COMMON_TEMPLATES, HUB_TEMPLATES

WEB_TEMPLATES = [
    "base.html", "login.html", "search.html",
    "docs.html", "doc.html", "section.html", "style.css",
]


def test_all_web_templates_exist_as_package_resources():
    base = resources.files("center_kb").joinpath("templates/web")
    for name in WEB_TEMPLATES:
        assert base.joinpath(name).is_file(), name


def test_all_init_templates_exist_as_package_resources():
    base = resources.files("center_kb").joinpath("templates/init")
    # CHILD_TEMPLATES resources land in the child-scaffold task (Task 3).
    for mapping in (COMMON_TEMPLATES, HUB_TEMPLATES):
        for resource_name in mapping.values():
            assert base.joinpath(resource_name).is_file(), resource_name
