"""PHP route adapters for `routes.py`: Laravel and Symfony.

`_routes_laravel` plays `Route::` statements under the prefixes the app
registers its route files with; `_routes_symfony` reads `#[Route]`
attributes and `@Route` docblock annotations, and the YAML that imports them.
"""

from __future__ import annotations

from strata_kb.codeingest.extractors import _routes_laravel, _routes_symfony

__all__ = ["ADAPTERS"]

ADAPTERS = {**_routes_laravel.ADAPTERS, **_routes_symfony.ADAPTERS}
