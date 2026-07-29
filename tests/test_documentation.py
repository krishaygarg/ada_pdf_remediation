"""Tests that the documentation matches the code.

Documentation drifts. These check the claims that would be embarrassing to get
wrong: the coverage figures, the commands that are advertised, and the rule
catalogue, which is generated and must not be edited into disagreement with the
registry.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def readme() -> str:
    return (ROOT / "README.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def contributing() -> str:
    return (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")


class TestCoverageClaims:
    def test_the_readme_states_the_implemented_count_correctly(self, readme: str) -> None:
        from remediator.audit import coverage_summary

        summary = coverage_summary()
        assert f"**{summary['implemented_conditions']} conditions across " in readme
        assert f"{summary['implemented_checkpoints']} of the 31 checkpoints**" in readme

    def test_the_protocol_totals_are_stated_correctly(self, readme: str) -> None:
        """31 checkpoints, 136 conditions, 87 software determinable."""
        assert "31 checkpoints and 136 failure conditions" in readme
        assert "87 can be determined by software" in readme

    def test_the_readme_does_not_claim_full_conformance(self, readme: str) -> None:
        """The claim the project exists not to make."""
        lowered = readme.lower()
        assert "100% compliant" not in lowered
        assert "fully accessible" not in lowered
        assert "will not tell you a document is accessible" in lowered

    def test_the_contributing_backlog_matches_the_remaining_count(self, contributing: str) -> None:
        from remediator.audit import MATTERHORN_SOFTWARE_CONDITIONS, coverage_summary

        remaining = MATTERHORN_SOFTWARE_CONDITIONS - coverage_summary()["implemented_conditions"]
        assert str(remaining) in contributing, (
            f"CONTRIBUTING should say {remaining} machine-checkable conditions remain"
        )


class TestAdvertisedCommands:
    @pytest.mark.parametrize("command", ["remediate-pdf", "check-compliance", "ada-ro-bench"])
    def test_every_advertised_command_exists(self, readme: str, command: str) -> None:
        import tomllib

        manifest = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        assert command in manifest["project"]["scripts"]
        assert command in readme

    def test_the_documented_flags_are_accepted(self) -> None:
        """Every flag shown in the reference has to actually parse."""
        from remediator.cli.compliance import build_parser

        parser = build_parser()
        documented = re.findall(
            r"`(--[a-z-]+)`", (ROOT / "docs" / "reference" / "cli.md").read_text(encoding="utf-8")
        )
        known = {option for action in parser._actions for option in action.option_strings}
        for flag in set(documented):
            if flag in ("--strategy", "--list-strategies", "--traceback"):
                continue  # belongs to another command
            assert flag in known, f"{flag} is documented but not accepted"


class TestGeneratedCatalogue:
    def test_the_catalogue_is_current(self, tmp_path: Path) -> None:
        """A page that disagrees with the tool is worse than no page."""
        target = tmp_path / "rules.md"
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "generate_rule_catalogue.py"), str(target)],
            check=True,
            capture_output=True,
            cwd=ROOT,
        )
        committed = (ROOT / "docs" / "reference" / "rules.md").read_text(encoding="utf-8")
        assert target.read_text(encoding="utf-8") == committed, (
            "docs/reference/rules.md is stale; run scripts/generate_rule_catalogue.py"
        )

    def test_every_registered_rule_appears(self) -> None:
        from remediator.audit import rule_catalogue

        page = (ROOT / "docs" / "reference" / "rules.md").read_text(encoding="utf-8")
        for metadata in rule_catalogue():
            assert f"`{metadata.condition}`" in page


class TestSiteIntegrity:
    def test_every_navigation_entry_exists(self) -> None:
        import yaml

        config = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
        # The Mermaid fence uses a Python-name tag mkdocs understands and a
        # plain YAML loader does not, so it is stripped before parsing.
        config = re.sub(r"!!python/name:\S+", "null", config)
        navigation = yaml.safe_load(config)["nav"]

        def walk(entries: object) -> list[str]:
            found: list[str] = []
            if isinstance(entries, list):
                for entry in entries:
                    found.extend(walk(entry))
            elif isinstance(entries, dict):
                for value in entries.values():
                    found.extend(walk(value))
            elif isinstance(entries, str):
                found.append(entries)
            return found

        for page in walk(navigation):
            assert (ROOT / "docs" / page).is_file(), f"nav points at a missing page: {page}"

    def test_internal_links_resolve(self) -> None:
        for source in (ROOT / "docs").rglob("*.md"):
            text = source.read_text(encoding="utf-8")
            for target in re.findall(r"\]\((?!https?:|#|mailto:)([^)#]+)", text):
                resolved = (source.parent / target).resolve()
                assert resolved.exists(), f"{source.name} links to a missing file: {target}"

    def test_readme_links_to_repository_files_resolve(self, readme: str) -> None:
        for target in re.findall(r"\]\((?!https?:|#|mailto:)([^)#]+)", readme):
            assert (ROOT / target).exists(), f"README links to a missing path: {target}"


class TestProse:
    @pytest.mark.parametrize(
        "document", ["README.md", "CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md"]
    )
    def test_no_em_dashes(self, document: str) -> None:
        """A house style choice, applied consistently."""
        text = (ROOT / document).read_text(encoding="utf-8")
        assert "—" not in text, f"{document} contains an em dash"

    def test_the_docs_site_avoids_them_too(self) -> None:
        # Recursive: the generated reference pages are the ones most likely to
        # reintroduce them, since a generator is easy to forget about.
        for source in (ROOT / "docs").rglob("*.md"):
            if "planning" in source.parts:
                continue  # the research specifications predate this convention
            assert "—" not in source.read_text(encoding="utf-8"), source.name

    def test_the_readme_opens_with_the_problem_not_the_tool(self, readme: str) -> None:
        opening = readme.split("\n\n")[1]
        assert "screen reader" in opening.lower()
