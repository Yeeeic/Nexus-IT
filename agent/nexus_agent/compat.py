"""Compatibility helpers for older Python runtimes (such as Python 3.8 on Windows 7)."""

from __future__ import annotations

import sys
from dataclasses import dataclass as _std_dataclass
from typing import Any, Callable


def dataclass(*args: Any, **kwargs: Any) -> Callable[[type], type]:
    """Wraps dataclass to gracefully ignore slots=True on Python < 3.10."""
    if sys.version_info < (3, 10):
        kwargs.pop("slots", None)
    return _std_dataclass(*args, **kwargs)


try:
    from typing import Protocol
except ImportError:
    from typing_extensions import Protocol  # type: ignore[assignment]
