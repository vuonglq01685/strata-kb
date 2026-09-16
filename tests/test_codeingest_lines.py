from center_kb.codeingest.extractors._lines import join_continuations


def test_backslash_continuations_are_joined_with_a_space():
    text = "docker build \\\n    --tag x:latest \\\n    .\npytest -q\n"
    assert join_continuations(text) == ["docker build --tag x:latest .", "pytest -q"]


def test_blank_and_comment_lines_are_dropped():
    assert join_continuations("# setup\n\n  # more\nruff check .\n") == ["ruff check ."]


def test_trailing_continuation_at_end_of_text_is_kept():
    assert join_continuations("echo a \\") == ["echo a"]


def test_comment_line_ending_in_backslash_does_not_swallow_the_next_line():
    # Fix wave, Finding 1: the continuation check used to run before the
    # comment drop, so a `#` line ending in `\` set `pending`, and the
    # join then re-tested `startswith("#")` on the merged string and
    # dropped both lines -- the real command after it vanished.
    text = "# run the linter \\\nruff check .\n"
    assert join_continuations(text) == ["ruff check ."]


def test_escaped_trailing_backslash_pair_is_not_a_continuation():
    # Fix wave, Finding 2: a line ending in `\\` (an escaped backslash,
    # not a line continuation in POSIX shell) used to be treated as one
    # anyway, merging two unrelated commands into one.
    text = "printf a\\\\\nruff check .\n"
    assert join_continuations(text) == ["printf a\\\\", "ruff check ."]
