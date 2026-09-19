"""Extractor registry for `kb code-ingest`.

Tasks B2-B7 each appended one `Extractor` instance here; as of Task B7
(the last extractor task) the set is complete, in this fixed, documented
order, so `core.run()`'s reports (detected / sections_by_extractor) read
the same way on every run:

    services, deps, commands, tree, schema, integrations, api
"""
from __future__ import annotations

from center_kb.codeingest.extractors.api import ApiExtractor
from center_kb.codeingest.extractors.commands import CommandsExtractor
from center_kb.codeingest.extractors.deps import DepsExtractor
from center_kb.codeingest.extractors.integrations import IntegrationsExtractor
from center_kb.codeingest.extractors.schema import SchemaExtractor
from center_kb.codeingest.extractors.services import ServicesExtractor
from center_kb.codeingest.extractors.tree import TreeExtractor

ALL_EXTRACTORS: list = [
    ServicesExtractor(), DepsExtractor(), CommandsExtractor(), TreeExtractor(),
    SchemaExtractor(), IntegrationsExtractor(), ApiExtractor(),
]
