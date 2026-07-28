"""Automated PDF accessibility remediation and conformance auditing.

The package turns untagged PDF documents into tagged documents targeting
PDF/UA-1 (ISO 14289-1) and WCAG 2.1, and audits the result.
"""

from __future__ import annotations

from importlib import metadata as _metadata
from typing import Any

try:
    __version__ = _metadata.version("ada-pdf-remediator")
except _metadata.PackageNotFoundError:  # pragma: no cover - source checkout
    __version__ = "0.0.0.dev0"

_LAZY_EXPORTS = {
    "remediate_single_pdf": ("remediator.pipeline", "remediate_single_pdf"),
    "run_compliance_check": ("remediator.compliance", "run_compliance_check"),
}


def __getattr__(name: str) -> Any:
    """Resolve the public API lazily.

    The PDF stack is expensive to import. Deferring it keeps ``import
    remediator`` cheap for callers that only need ``__version__``, which is the
    common case during CLI startup, health checks and test collection.
    """
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(target[0]), target[1])


def __dir__() -> list[str]:
    return sorted(__all__)


__all__ = ["__version__", "remediate_single_pdf", "run_compliance_check"]
