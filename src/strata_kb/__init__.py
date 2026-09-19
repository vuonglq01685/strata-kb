from importlib.metadata import PackageNotFoundError, version as _dist_version

try:
    __version__ = _dist_version("strata-kb")
except PackageNotFoundError:  # running from a source tree with no install
    __version__ = "0+unknown"
