"""
Typed Python client for the weclapp REST API v2, focused on the endpoints needed to synchronise employee master data.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _distribution_version

try:
    __version__ = _distribution_version("weclapp-client")
except PackageNotFoundError:  # pragma: no cover - only happens when the package is used without being installed
    __version__ = "0.0.0"

__all__ = ["__version__"]
