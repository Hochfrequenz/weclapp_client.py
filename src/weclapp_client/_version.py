"""
Version of the installed distribution (derived from git tags by hatch-vcs at build time).
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("weclapp-client")
except PackageNotFoundError:  # pragma: no cover - only happens when the package is used without being installed
    __version__ = "0.0.0"
