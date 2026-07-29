"""Provider registration and discovery.

Providers can be registered in process or shipped from a separate distribution
through the ``ada_pdf_remediator.alttext`` entry point group. The second route
matters for the research track: an experiment can be installed alongside the
package and selected by name, without a change to this repository.
"""

from __future__ import annotations

from functools import cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - imported for annotations only
    from .base import AltTextProvider

ENTRY_POINT_GROUP = "ada_pdf_remediator.alttext"

_PROVIDERS: dict[str, AltTextProvider] = {}


def register_provider(provider: AltTextProvider, *, replace: bool = False) -> None:
    """Make ``provider`` selectable by name."""
    name = provider.name
    if not name:
        raise ValueError("a provider must declare a non-empty name")
    if name in _PROVIDERS and not replace:
        raise ValueError(f"a provider named {name!r} is already registered")
    _PROVIDERS[name] = provider


@cache
def _load_entry_points() -> None:
    """Import every registered provider distribution, once per process.

    Cached rather than guarded by a module-level flag. Scanning entry points is
    the kind of work that must not repeat on every lookup, and a memo the
    language maintains cannot fall out of step with the branch that reads it.
    """
    from importlib.metadata import entry_points

    for entry in entry_points(group=ENTRY_POINT_GROUP):
        try:
            candidate = entry.load()
            provider = candidate() if isinstance(candidate, type) else candidate
            register_provider(provider, replace=True)
        except Exception:
            # A broken third-party provider must not prevent remediation. It is
            # simply absent from the list, which is visible to the caller.
            continue


def available_providers() -> dict[str, AltTextProvider]:
    """Every registered provider, keyed by name."""
    _ensure_defaults()
    _load_entry_points()
    return dict(_PROVIDERS)


def get_provider(name: str | None = None) -> AltTextProvider:
    """Return a provider by name, or the default when no name is given."""
    providers = available_providers()
    if name is None:
        return providers["needs-review"]
    try:
        return providers[name]
    except KeyError:
        known = ", ".join(sorted(providers)) or "none"
        raise LookupError(f"no alternate text provider named {name!r}; known: {known}") from None


def _ensure_defaults() -> None:
    if "needs-review" not in _PROVIDERS:
        from .review import NeedsReviewProvider

        _PROVIDERS["needs-review"] = NeedsReviewProvider()


__all__ = ["ENTRY_POINT_GROUP", "available_providers", "get_provider", "register_provider"]
