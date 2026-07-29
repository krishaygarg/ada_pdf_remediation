"""Rule registration and the audit runner.

A rule is a function that receives a :class:`DocumentContext` and yields
:class:`Finding` objects. Registering one is a decorator plus a metadata
literal, which is the whole extension surface: contributors adding a Matterhorn
condition write a predicate and a fixture, not another pass over the document.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

import pikepdf

from .context import DocumentContext
from .model import Determination, Finding, Report, RuleMetadata, Severity

RuleFunction = Callable[[DocumentContext], Iterable[Finding]]

_CONDITION_PATTERN = re.compile(r"^\d{2}-\d{3}$")

#: Checkpoints whose rules render pages, which costs orders of magnitude more
#: than reading the object graph. They run only when asked for by name, so the
#: default audit stays fast enough to sit in a commit hook.
EXPENSIVE_CHECKPOINTS = frozenset({"04"})

#: condition identifier -> (metadata, function)
_REGISTRY: dict[str, tuple[RuleMetadata, RuleFunction]] = {}


def rule(metadata: RuleMetadata) -> Callable[[RuleFunction], RuleFunction]:
    """Register a conformance rule under its Matterhorn failure condition."""

    def decorate(function: RuleFunction) -> RuleFunction:
        if not _CONDITION_PATTERN.match(metadata.condition):
            raise ValueError(
                f"condition {metadata.condition!r} must look like '13-004' "
                "(two digit checkpoint, three digit condition)"
            )
        if metadata.condition in _REGISTRY:
            existing = _REGISTRY[metadata.condition][1]
            raise ValueError(
                f"condition {metadata.condition} is already registered by "
                f"{existing.__module__}.{existing.__qualname__}"
            )
        _REGISTRY[metadata.condition] = (metadata, function)
        return function

    return decorate


def registered_rules() -> dict[str, tuple[RuleMetadata, RuleFunction]]:
    """All registered rules, ordered by condition identifier."""
    _load_rule_modules()
    return dict(sorted(_REGISTRY.items()))


def rule_catalogue() -> list[RuleMetadata]:
    """Metadata for every registered rule, for documentation generation."""
    return [metadata for metadata, _ in registered_rules().values()]


_LOADED = False


def _load_rule_modules() -> None:
    """Import the rule packages so their decorators run."""
    global _LOADED
    if _LOADED:
        return
    from importlib import import_module
    from pkgutil import iter_modules

    from . import rules

    for module in iter_modules(rules.__path__):
        import_module(f"{rules.__name__}.{module.name}")
    _LOADED = True


def audit_document(
    path: Path | str,
    *,
    include: Iterable[str] | None = None,
    exclude: Iterable[str] | None = None,
) -> Report:
    """Run every registered rule against ``path`` and collect the findings.

    Args:
        path: The document to audit.
        include: Restrict the run to these conditions or checkpoints. A two
            digit value selects a whole checkpoint.
        exclude: Skip these conditions or checkpoints.
    """
    path = Path(path)
    report = Report(document=str(path))

    selected = _select(registered_rules(), include, exclude)

    try:
        pdf_context = pikepdf.open(path)
    except Exception as exc:
        report.findings.append(
            Finding(
                condition="00-001",
                message=f"The document could not be opened: {exc}",
                severity=Severity.ERROR,
            )
        )
        return report

    with pdf_context as pdf:
        context = DocumentContext(pdf, path)
        for condition, (metadata, function) in selected.items():
            report.rules_run += 1
            try:
                for finding in function(context):
                    report.findings.append(finding)
            except Exception as exc:
                # Recording the failure keeps a crashed check from being
                # indistinguishable from a check that found nothing.
                report.rules_errored[condition] = f"{type(exc).__name__}: {exc}"
            _ = metadata

    report.findings.sort(key=lambda f: (f.condition, f.location.page or -1, f.message))
    return report


def _select(
    rules: dict[str, tuple[RuleMetadata, RuleFunction]],
    include: Iterable[str] | None,
    exclude: Iterable[str] | None,
) -> dict[str, tuple[RuleMetadata, RuleFunction]]:
    include_set = set(include) if include else None
    exclude_set = set(exclude) if exclude else set()

    def matches(condition: str, selectors: set[str]) -> bool:
        return condition in selectors or condition.split("-", 1)[0] in selectors

    def wanted(condition: str) -> bool:
        checkpoint = condition.split("-", 1)[0]
        if matches(condition, exclude_set):
            return False
        if include_set is not None:
            return matches(condition, include_set)
        # An expensive checkpoint is opt-in, so it is absent from a default run
        # unless the caller named it.
        return checkpoint not in EXPENSIVE_CHECKPOINTS

    return {condition: entry for condition, entry in rules.items() if wanted(condition)}


def iter_human_checks() -> Iterator[RuleMetadata]:
    """Conditions the Matterhorn Protocol says a person has to judge."""
    for metadata in rule_catalogue():
        if metadata.determination is Determination.HUMAN:
            yield metadata


__all__ = [
    "RuleFunction",
    "audit_document",
    "iter_human_checks",
    "registered_rules",
    "rule",
    "rule_catalogue",
]
