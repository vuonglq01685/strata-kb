"""YAML loading for Docker Compose files: `yaml.safe_load` plus Compose's
merge tags `!reset` and `!override` (Compose spec, "Merge and override").

A plain `SafeLoader` has no constructor for either tag and raises
`ConstructorError` for the whole file, so one `!reset` line used to drop
every service and env key the file declares. Every other tag still fails
exactly as it does under `yaml.safe_load`.
"""

from __future__ import annotations

import yaml


class _ComposeLoader(yaml.SafeLoader):
    """SafeLoader that also understands Compose's `!reset` / `!override`."""


def _reset(loader: _ComposeLoader, node: yaml.Node) -> object:
    # `!reset` clears the value an earlier file set; for topology that is
    # the empty value of the node's own kind.
    if isinstance(node, yaml.SequenceNode):
        return []
    if isinstance(node, yaml.MappingNode):
        return {}
    return None


def _override(loader: _ComposeLoader, node: yaml.Node) -> object:
    # `!override` replaces instead of merging; the value itself is plain.
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    # A plain (unquoted) scalar resolves implicitly, same as `!override 3` ->
    # int 3 under `yaml.safe_load`; a quoted scalar (`node.style` set) must
    # not -- `resolve`'s hard-coded (True, False) used to force even a quoted
    # `"3"` / `"1.10"` through the implicit-tag resolver, turning them into
    # int 3 / float 1.1 instead of staying strings like `yaml.safe_load`
    # itself leaves them.
    implicit = (node.style is None, node.style is not None)
    tag = loader.resolve(yaml.ScalarNode, node.value, implicit)
    return loader.yaml_constructors[tag](loader, node)


_ComposeLoader.add_constructor("!reset", _reset)
_ComposeLoader.add_constructor("!override", _override)


def load_compose(text: str) -> object:
    """`yaml.safe_load` for a compose file, `!reset`/`!override` included."""
    return yaml.load(text, Loader=_ComposeLoader)  # noqa: S506 - SafeLoader subclass
