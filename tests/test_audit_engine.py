"""Tests for the conformance rule engine itself.

The engine has to be trustworthy before its verdicts mean anything, so these
cover the machinery as well as the rules: registration, isolation of a failing
rule, selection, and each report format.
"""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest

from remediator.audit import (
    MATTERHORN_CONDITIONS,
    Determination,
    Finding,
    Location,
    RemediationStatus,
    Report,
    Severity,
    audit_document,
    coverage_summary,
    registered_rules,
    rule_catalogue,
)
from remediator.audit.reporters import render, to_dict
from remediator.pipeline import remediate_single_pdf


@pytest.fixture
def remediated(make_text_pdf: object, tmp_path: Path) -> Path:
    source = make_text_pdf(pages=2)  # type: ignore[operator]
    target = tmp_path / "remediated.pdf"
    remediate_single_pdf(str(source), str(target))
    return target


class TestRegistry:
    def test_rules_are_registered(self) -> None:
        assert registered_rules()

    def test_every_condition_identifier_is_well_formed(self) -> None:
        import re

        for metadata in rule_catalogue():
            assert re.match(r"^\d{2}-\d{3}$", metadata.condition), metadata.condition

    def test_condition_identifiers_are_unique(self) -> None:
        conditions = [metadata.condition for metadata in rule_catalogue()]
        assert len(conditions) == len(set(conditions))

    def test_every_rule_names_its_checkpoint_and_summary(self) -> None:
        for metadata in rule_catalogue():
            assert metadata.checkpoint_name.strip()
            assert metadata.summary.strip()

    def test_coverage_is_reported_honestly(self) -> None:
        """The engine must not imply it covers more of the protocol than it does."""
        summary = coverage_summary()
        assert 0 < summary["implemented_conditions"] <= MATTERHORN_CONDITIONS
        assert summary["protocol_conditions"] == 136
        assert summary["protocol_software_conditions"] == 87
        assert summary["implemented_conditions"] < summary["protocol_software_conditions"]

    def test_registering_a_duplicate_condition_is_refused(self) -> None:
        from remediator.audit.model import RuleMetadata
        from remediator.audit.registry import rule

        existing = rule_catalogue()[0].condition
        with pytest.raises(ValueError, match="already registered"):

            @rule(RuleMetadata(condition=existing, checkpoint_name="X", summary="duplicate"))
            def _duplicate(context):  # pragma: no cover - registration raises first
                yield from ()

    def test_a_malformed_condition_identifier_is_refused(self) -> None:
        from remediator.audit.model import RuleMetadata
        from remediator.audit.registry import rule

        with pytest.raises(ValueError, match="two digit checkpoint"):

            @rule(RuleMetadata(condition="bogus", checkpoint_name="X", summary="bad"))
            def _bad(context):  # pragma: no cover - registration raises first
                yield from ()


class TestRunner:
    def test_a_missing_file_is_reported_rather_than_raising(self, tmp_path: Path) -> None:
        report = audit_document(tmp_path / "absent.pdf")
        assert not report.conformant
        assert report.findings[0].condition == "00-001"

    def test_a_damaged_file_is_reported_rather_than_raising(self, tmp_path: Path) -> None:
        broken = tmp_path / "broken.pdf"
        broken.write_bytes(b"%PDF-1.7\nthis is not a pdf")
        report = audit_document(broken)
        assert not report.conformant

    def test_a_crashing_rule_is_recorded_not_swallowed(
        self, remediated: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A check that fails to run must never look like a check that passed."""
        from remediator.audit import registry

        def exploding(context):
            raise RuntimeError("deliberate failure")
            yield  # pragma: no cover

        real = registry.registered_rules()
        first = next(iter(real))
        patched = dict(real)
        patched[first] = (real[first][0], exploding)
        monkeypatch.setattr(registry, "registered_rules", lambda: patched)

        report = registry.audit_document(remediated)
        assert first in report.rules_errored
        assert "deliberate failure" in report.rules_errored[first]
        assert not report.conformant, "a document with an unrun check cannot be declared clean"

    def test_selection_by_checkpoint(self, remediated: Path) -> None:
        report = audit_document(remediated, include=["10"])
        assert report.rules_run > 0
        assert all(f.checkpoint == "10" for f in report.findings)

    def test_selection_by_condition(self, remediated: Path) -> None:
        report = audit_document(remediated, include=["10-003"])
        assert report.rules_run == 1

    def test_exclusion_removes_rules(self, remediated: Path) -> None:
        everything = audit_document(remediated)
        without = audit_document(remediated, exclude=["10"])
        assert without.rules_run < everything.rules_run
        assert not [f for f in without.findings if f.checkpoint == "10"]

    def test_findings_are_ordered_deterministically(self, remediated: Path) -> None:
        first = [(f.condition, f.message) for f in audit_document(remediated).findings]
        second = [(f.condition, f.message) for f in audit_document(remediated).findings]
        assert first == second


class TestRulesDetectRealDefects:
    """Each rule is exercised against a document that actually violates it."""

    def _audit_after_mutation(self, path: Path, mutate, condition: str):
        with pikepdf.open(path, allow_overwriting_input=True) as pdf:
            mutate(pdf)
            pdf.save(path)
        return audit_document(path, include=[condition])

    def test_missing_language_is_detected(self, remediated: Path) -> None:
        report = self._audit_after_mutation(
            remediated, lambda pdf: pdf.Root.__delitem__("/Lang"), "11-001"
        )
        assert [f.condition for f in report.errors] == ["11-001"]

    def test_a_malformed_language_tag_is_detected(self, remediated: Path) -> None:
        def mutate(pdf):
            pdf.Root["/Lang"] = pikepdf.String("english please")

        report = self._audit_after_mutation(remediated, mutate, "11-006")
        assert report.errors

    def test_missing_mark_info_is_detected(self, remediated: Path) -> None:
        report = self._audit_after_mutation(
            remediated, lambda pdf: pdf.Root.__delitem__("/MarkInfo"), "07-001"
        )
        assert report.errors

    def test_suspects_flag_is_detected(self, remediated: Path) -> None:
        def mutate(pdf):
            pdf.Root.MarkInfo["/Suspects"] = True

        report = self._audit_after_mutation(remediated, mutate, "07-002")
        assert report.errors

    def test_display_doc_title_disabled_is_detected(self, remediated: Path) -> None:
        def mutate(pdf):
            pdf.Root.ViewerPreferences["/DisplayDocTitle"] = False

        report = self._audit_after_mutation(remediated, mutate, "06-003")
        assert report.errors

    def test_the_wrong_pdfua_namespace_is_detected(self, remediated: Path) -> None:
        """The exact defect this project shipped, now caught by the auditor."""

        def mutate(pdf):
            text = pdf.Root.Metadata.read_bytes().decode("utf-8")
            text = text.replace(
                "http://www.aiim.org/pdfua/ns/id/", "http://www.aiim.org/pdfuaid/ns/id/"
            )
            stream = pikepdf.Stream(pdf, text.encode("utf-8"))
            stream.Type = pikepdf.Name("/Metadata")
            stream.Subtype = pikepdf.Name("/XML")
            pdf.Root["/Metadata"] = stream

        report = self._audit_after_mutation(remediated, mutate, "06-004")
        assert report.errors
        assert "pdfuaid/ns/id" in report.errors[0].message

    def test_a_missing_structure_tree_is_detected(self, remediated: Path) -> None:
        report = self._audit_after_mutation(
            remediated, lambda pdf: pdf.Root.__delitem__("/StructTreeRoot"), "01-003"
        )
        assert report.errors

    def test_a_figure_without_alternate_text_is_detected(self, remediated: Path) -> None:
        def mutate(pdf):
            figure = pdf.make_indirect(
                pikepdf.Dictionary(
                    Type=pikepdf.Name("/StructElem"),
                    S=pikepdf.Name("/Figure"),
                    K=pikepdf.Integer(0),
                )
            )
            pdf.Root.StructTreeRoot.K.K.append(figure)

        report = self._audit_after_mutation(remediated, mutate, "13-004")
        assert report.errors

    def test_uninformative_alternate_text_is_flagged_as_a_warning(self, remediated: Path) -> None:
        def mutate(pdf):
            figure = pdf.make_indirect(
                pikepdf.Dictionary(
                    Type=pikepdf.Name("/StructElem"),
                    S=pikepdf.Name("/Figure"),
                    Alt=pikepdf.String("image"),
                    K=pikepdf.Integer(0),
                )
            )
            pdf.Root.StructTreeRoot.K.K.append(figure)

        report = self._audit_after_mutation(remediated, mutate, "13-005")
        assert report.warnings
        assert not report.errors, "a poor description conforms; it is still worth reporting"

    def test_alternate_text_that_is_a_file_name_is_flagged(self, remediated: Path) -> None:
        def mutate(pdf):
            figure = pdf.make_indirect(
                pikepdf.Dictionary(
                    Type=pikepdf.Name("/StructElem"),
                    S=pikepdf.Name("/Figure"),
                    Alt=pikepdf.String("fig_03_final_v2.png"),
                    K=pikepdf.Integer(0),
                )
            )
            pdf.Root.StructTreeRoot.K.K.append(figure)

        report = self._audit_after_mutation(remediated, mutate, "13-005")
        assert report.warnings

    def test_a_skipped_heading_level_is_detected(self, remediated: Path) -> None:
        def mutate(pdf):
            for tag in ("/H1", "/H3"):
                pdf.Root.StructTreeRoot.K.K.append(
                    pdf.make_indirect(
                        pikepdf.Dictionary(
                            Type=pikepdf.Name("/StructElem"),
                            S=pikepdf.Name(tag),
                            K=pikepdf.Integer(0),
                        )
                    )
                )

        report = self._audit_after_mutation(remediated, mutate, "14-002")
        assert report.errors
        assert "skipping level 2" in report.errors[0].message

    def test_a_table_without_headers_is_detected(self, remediated: Path) -> None:
        def mutate(pdf):
            cell = pdf.make_indirect(
                pikepdf.Dictionary(Type=pikepdf.Name("/StructElem"), S=pikepdf.Name("/TD"))
            )
            row = pdf.make_indirect(
                pikepdf.Dictionary(
                    Type=pikepdf.Name("/StructElem"),
                    S=pikepdf.Name("/TR"),
                    K=pikepdf.Array([cell]),
                )
            )
            table = pdf.make_indirect(
                pikepdf.Dictionary(
                    Type=pikepdf.Name("/StructElem"),
                    S=pikepdf.Name("/Table"),
                    K=pikepdf.Array([row]),
                )
            )
            pdf.Root.StructTreeRoot.K.K.append(table)

        report = self._audit_after_mutation(remediated, mutate, "15-003")
        assert report.errors

    def test_a_cell_outside_a_row_is_detected(self, remediated: Path) -> None:
        def mutate(pdf):
            cell = pdf.make_indirect(
                pikepdf.Dictionary(Type=pikepdf.Name("/StructElem"), S=pikepdf.Name("/TD"))
            )
            table = pdf.make_indirect(
                pikepdf.Dictionary(
                    Type=pikepdf.Name("/StructElem"),
                    S=pikepdf.Name("/Table"),
                    K=pikepdf.Array([cell]),
                )
            )
            pdf.Root.StructTreeRoot.K.K.append(table)

        report = self._audit_after_mutation(remediated, mutate, "15-006")
        assert report.errors

    def test_a_list_item_outside_a_list_is_detected(self, remediated: Path) -> None:
        def mutate(pdf):
            item = pdf.make_indirect(
                pikepdf.Dictionary(Type=pikepdf.Name("/StructElem"), S=pikepdf.Name("/LI"))
            )
            pdf.Root.StructTreeRoot.K.K.append(item)

        report = self._audit_after_mutation(remediated, mutate, "16-001")
        assert report.errors

    def test_an_unmapped_custom_structure_type_is_detected(self, remediated: Path) -> None:
        def mutate(pdf):
            custom = pdf.make_indirect(
                pikepdf.Dictionary(
                    Type=pikepdf.Name("/StructElem"), S=pikepdf.Name("/CompanyHeading")
                )
            )
            pdf.Root.StructTreeRoot.K.K.append(custom)

        report = self._audit_after_mutation(remediated, mutate, "02-001")
        assert report.errors

    def test_a_circular_role_map_is_detected(self, remediated: Path) -> None:
        def mutate(pdf):
            pdf.Root.StructTreeRoot["/RoleMap"] = pikepdf.Dictionary(
                Alpha=pikepdf.Name("/Beta"), Beta=pikepdf.Name("/Alpha")
            )

        report = self._audit_after_mutation(remediated, mutate, "02-003")
        assert report.errors

    def test_a_degenerate_character_map_is_detected(self, remediated: Path) -> None:
        """A /ToUnicode map full of spaces satisfies a presence check and nothing more."""

        def mutate(pdf):
            entries = "".join(f"<{code:02X}> <0020>\n" for code in range(64))
            cmap = (
                "/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
                "/CMapName /Broken def\n/CMapType 2 def\n"
                "1 begincodespacerange <00> <FF> endcodespacerange\n"
                f"64 beginbfchar\n{entries}endbfchar\nendcmap\nend\nend"
            )
            for page in pdf.pages:
                fonts = page.obj["/Resources"]["/Font"]
                for key in fonts:
                    fonts[key]["/ToUnicode"] = pikepdf.Stream(pdf, cmap.encode("ascii"))

        report = self._audit_after_mutation(remediated, mutate, "10-003")
        assert report.errors
        assert "space or replacement character" in report.errors[0].message

    def test_a_font_without_a_character_map_is_detected(self, remediated: Path) -> None:
        def mutate(pdf):
            for page in pdf.pages:
                fonts = page.obj["/Resources"]["/Font"]
                for key in fonts:
                    if "/ToUnicode" in fonts[key]:
                        del fonts[key]["/ToUnicode"]

        report = self._audit_after_mutation(remediated, mutate, "10-001")
        assert report.errors

    def test_an_unembedded_font_is_detected(self, remediated: Path) -> None:
        report = audit_document(remediated, include=["31-001"])
        assert report.errors, "the generated fixture uses a standard font with no program"


class TestAnnotationRules:
    def test_a_link_without_contents_is_detected(self, linked_pdf: Path, tmp_path: Path) -> None:
        target = tmp_path / "out.pdf"
        remediate_single_pdf(str(linked_pdf), str(target))
        with pikepdf.open(target, allow_overwriting_input=True) as pdf:
            del pdf.pages[0]["/Annots"][0]["/Contents"]
            pdf.save(target)
        report = audit_document(target, include=["28-011"])
        assert report.errors

    def test_a_colliding_structure_parent_key_is_detected(
        self, linked_pdf: Path, tmp_path: Path
    ) -> None:
        target = tmp_path / "out.pdf"
        remediate_single_pdf(str(linked_pdf), str(target))
        with pikepdf.open(target, allow_overwriting_input=True) as pdf:
            pdf.pages[0]["/Annots"][0]["/StructParent"] = pdf.pages[0]["/StructParents"]
            pdf.save(target)
        report = audit_document(target, include=["28-006"])
        assert report.errors
        assert "one key cannot resolve" in report.errors[0].message.lower()

    def test_a_correctly_tagged_link_produces_no_findings(
        self, linked_pdf: Path, tmp_path: Path
    ) -> None:
        target = tmp_path / "out.pdf"
        remediate_single_pdf(str(linked_pdf), str(target))
        report = audit_document(target, include=["28"])
        assert not report.errors, [f.message for f in report.errors]


class TestReporters:
    def test_text_report_names_the_document(self, remediated: Path) -> None:
        output = render(audit_document(remediated), "text")
        assert remediated.name in output

    def test_text_report_has_no_escape_codes_when_colour_is_disabled(
        self, remediated: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.delenv("FORCE_COLOR", raising=False)
        assert "\033[" not in render(audit_document(remediated), "text")

    def test_json_report_round_trips(self, remediated: Path) -> None:
        import json

        payload = json.loads(render(audit_document(remediated), "json"))
        assert payload["document"].endswith("remediated.pdf")
        assert isinstance(payload["findings"], list)
        assert set(payload["counts"]) == {"errors", "warnings", "review"}

    def test_sarif_is_valid_and_references_its_rules(self, remediated: Path) -> None:
        import json

        report = audit_document(remediated)
        document = json.loads(render(report, "sarif"))
        assert document["version"] == "2.1.0"
        run = document["runs"][0]
        declared = {rule["id"] for rule in run["tool"]["driver"]["rules"]}
        used = {result["ruleId"] for result in run["results"]}
        assert used <= declared, "every result must reference a declared rule"
        for result in run["results"]:
            assert result["level"] in {"error", "warning", "note"}

    def test_sarif_carries_the_wcag_cross_reference(self, remediated: Path) -> None:
        import json

        document = json.loads(render(audit_document(remediated), "sarif"))
        rules = document["runs"][0]["tool"]["driver"]["rules"]
        assert any("wcag" in rule.get("properties", {}) for rule in rules)

    def test_junit_is_valid_xml_with_a_case_per_rule(self, remediated: Path) -> None:
        from xml.etree import ElementTree as ET

        suite = ET.fromstring(render(audit_document(remediated), "junit"))
        assert suite.tag == "testsuite"
        assert len(suite.findall("testcase")) == len(rule_catalogue())

    def test_an_unknown_format_is_refused(self, remediated: Path) -> None:
        with pytest.raises(ValueError, match="unknown report format"):
            render(audit_document(remediated), "yaml")

    def test_to_dict_is_json_serialisable(self, remediated: Path) -> None:
        import json

        json.dumps(to_dict(audit_document(remediated)))


class TestModel:
    def test_a_report_with_an_unrun_rule_is_not_conformant(self) -> None:
        report = Report(document="x.pdf", rules_errored={"13-004": "boom"})
        assert not report.conformant

    def test_warnings_alone_do_not_block_conformance(self) -> None:
        report = Report(
            document="x.pdf",
            findings=[Finding(condition="13-005", message="weak", severity=Severity.WARNING)],
        )
        assert report.conformant

    def test_location_describes_what_it_knows(self) -> None:
        assert Location().describe() == "document"
        assert Location(page=0).describe() == "page 1"
        assert "/Document/P" in Location(struct_path="/Document/P").describe()

    def test_severity_maps_onto_sarif_levels(self) -> None:
        assert Severity.ERROR.sarif_level == "error"
        assert Severity.WARNING.sarif_level == "warning"
        assert Severity.REVIEW.sarif_level == "note"

    def test_human_determination_is_representable(self) -> None:
        assert Determination.HUMAN.value == "human"


class TestReportsDoNotLeakServerPaths:
    def test_sarif_names_the_document_not_its_path(self, remediated: Path) -> None:
        """A SARIF file is uploaded to GitHub and kept, so an absolute path
        would publish the layout of whatever machine ran the audit."""
        import json

        document = json.loads(render(audit_document(remediated), "sarif"))
        for result in document["runs"][0]["results"]:
            uri = result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
            assert "/" not in uri and "\\" not in uri, f"the SARIF exposes a path: {uri}"
            assert uri == remediated.name


class TestRemediationStatus:
    """Severity says how bad a finding is. Repair status says what was done
    about it. A report carrying only severity cannot distinguish a finding
    nobody tried to fix from one a fix was attempted on and failed, and those
    call for opposite next actions."""

    @staticmethod
    def _finding(**kwargs: object) -> Finding:
        return Finding(condition="13-004", message="A figure has no alternate text.", **kwargs)  # type: ignore[arg-type]

    def test_a_finding_starts_as_unattempted(self) -> None:
        """The default has to be honest for the rules that have no repair yet,
        which is all of them: adding an autofix later must not retroactively
        reclassify findings already produced."""
        assert self._finding().remediation is RemediationStatus.NOT_ATTEMPTED
        assert self._finding().remediation_detail is None

    def test_only_a_remediated_finding_counts_as_resolved(self) -> None:
        assert RemediationStatus.REMEDIATED.resolved
        for status in (
            RemediationStatus.NOT_ATTEMPTED,
            RemediationStatus.FAILED,
            RemediationStatus.NEEDS_PERSON,
        ):
            assert not status.resolved, status
            assert status.needs_action, status

    def test_a_failed_repair_is_distinguishable_from_an_untouched_one(self) -> None:
        untouched = self._finding()
        failed = self._finding().as_failed("the font program has no glyph names")
        assert untouched.remediation is not failed.remediation
        assert failed.remediation_detail == "the font program has no glyph names"
        assert failed.remediation.needs_action

    def test_marking_a_finding_does_not_mutate_the_original(self) -> None:
        """Finding is frozen, so the helpers have to return a new one."""
        original = self._finding()
        repaired = original.as_remediated("added /Alt from the caption")
        assert original.remediation is RemediationStatus.NOT_ATTEMPTED
        assert repaired.remediation is RemediationStatus.REMEDIATED
        assert repaired.condition == original.condition
        assert repaired.message == original.message

    def test_a_human_judgement_finding_has_its_own_terminus(self) -> None:
        """Not FAILED. Nothing went wrong; automation should not decide it."""
        finding = self._finding().as_needing_a_person("what the chart means")
        assert finding.remediation is RemediationStatus.NEEDS_PERSON
        assert finding.remediation.needs_action

    def test_a_report_partitions_findings_by_what_was_done(self) -> None:
        report = Report(
            document="d.pdf",
            findings=[
                self._finding().as_remediated(),
                self._finding().as_failed("no glyph names"),
                self._finding().as_needing_a_person(),
                self._finding(),
            ],
        )
        assert len(report.remediated) == 1
        assert len(report.failed_remediations) == 1
        assert len(report.outstanding) == 3, "everything except the repaired one"

    def test_the_summary_reports_every_status_including_the_zeroes(self) -> None:
        """A summary that omits `failed` when the count is zero cannot be told
        apart from one produced before the field existed."""
        summary = Report(document="d.pdf", findings=[self._finding()]).remediation_summary()
        assert set(summary) == {status.value for status in RemediationStatus}
        assert summary["not_attempted"] == 1
        assert summary["failed"] == 0

    def test_repair_status_does_not_decide_conformance(self) -> None:
        """Conformance is a property of the document as it stands. A remediated
        error should no longer be reported as an error at all, so counting it
        against conformance would mean the status is wrong."""
        report = Report(
            document="d.pdf",
            findings=[self._finding(severity=Severity.ERROR).as_remediated()],
        )
        assert not report.conformant, "the error is still present in the findings list"

    def test_the_status_reaches_the_structured_report(self) -> None:
        report = Report(
            document="d.pdf",
            findings=[self._finding().as_failed("the font program has no glyph names")],
        )
        payload = to_dict(report)
        assert payload["remediation"]["failed"] == 1
        assert payload["findings"][0]["remediation"] == "failed"
        assert payload["findings"][0]["remediationDetail"] == "the font program has no glyph names"

    def test_the_published_api_description_lists_every_status(self) -> None:
        """The enum and the OpenAPI document must not drift apart."""
        from remediator.service.openapi import build_spec

        schemas = build_spec("0.0.0")["components"]["schemas"]
        advertised = schemas["Finding"]["properties"]["remediation"]["enum"]
        assert set(advertised) == {status.value for status in RemediationStatus}
        assert set(schemas["AuditReport"]["properties"]["remediation"]["properties"]) == set(
            advertised
        )
