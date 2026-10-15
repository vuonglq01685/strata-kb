"""Extractor registry for `kb code-ingest`.

One `Extractor` instance per extractor, in this fixed, documented order,
so `core.run()`'s reports (detected / sections_by_extractor) read the
same way on every run:

    services, deps, commands, tree, schema, integrations, api, routes, pages
"""

from __future__ import annotations

from strata_kb.codeingest.extractors.api import ApiExtractor
from strata_kb.codeingest.extractors.commands import CommandsExtractor
from strata_kb.codeingest.extractors.deps import DepsExtractor
from strata_kb.codeingest.extractors.integrations import IntegrationsExtractor
from strata_kb.codeingest.extractors.pages import PagesExtractor
from strata_kb.codeingest.extractors.routes import RoutesExtractor
from strata_kb.codeingest.extractors.schema import SchemaExtractor
from strata_kb.codeingest.extractors.services import ServicesExtractor
from strata_kb.codeingest.extractors.tree import TreeExtractor

ALL_EXTRACTORS: list = [
    ServicesExtractor(),
    DepsExtractor(),
    CommandsExtractor(),
    TreeExtractor(),
    SchemaExtractor(),
    IntegrationsExtractor(),
    ApiExtractor(),
    RoutesExtractor(),
    PagesExtractor(),
]
