from center_kb.codeingest.extractors._lines import join_continuations


def test_backslash_continuations_are_joined_with_a_space():
    text = "docker build \\\n    --tag x:latest \\\n    .\npytest -q\n"
    assert join_continuations(text) == ["docker build --tag x:latest .", "pytest -q"]


def test_blank_and_comment_lines_are_dropped():
    assert join_continuations("# setup\n\n  # more\nruff check .\n") == ["ruff check ."]


def test_trailing_continuation_at_end_of_text_is_kept():
    assert join_continuations("echo a \\") == ["echo a"]
