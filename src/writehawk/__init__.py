"""Finds Windows processes that rewrite the same file in a loop."""
import sys
from importlib.metadata import PackageNotFoundError, version

if sys.platform != "win32":
    raise ImportError("writehawk runs on Windows 10 and Windows 11 only")

try:
    __version__ = version("writehawk")
except PackageNotFoundError:  # running from a checkout that was never installed
    __version__ = "0+checkout"
