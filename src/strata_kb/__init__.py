"""strata_kb — a layered (L0-L3) knowledge base built from source documents.

The package root only exposes `__version__`, read from the installed
distribution metadata; it falls back to "0+unknown" in a source tree with no
install. The `kb` command line lives in `strata_kb.cli`.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version

try:
    __version__ = _dist_version("strata-kb")
except PackageNotFoundError:  # running from a source tree with no install
    __version__ = "0+unknown"
