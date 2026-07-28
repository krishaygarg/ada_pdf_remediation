"""Tests for the web interface.

These check the things that are cheap to assert and expensive to notice by
eye: that the markup is well formed and accessible, that the content security
policy the server sends is actually satisfiable by the page it serves, and that
the interface renders results rather than asserting them.

Behavioural accessibility (focus order under a real engine, computed contrast
after cascade) is covered by axe-core and Lighthouse in CI, which need a
browser this suite deliberately does not require.
"""

from __future__ import annotations

import json
import re
from itertools import pairwise
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

WEB = Path(__file__).resolve().parent.parent / "web"


@pytest.fixture(scope="module")
def html() -> str:
    return (WEB / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def css() -> str:
    return (WEB / "styles.css").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def script() -> str:
    return (WEB / "app.js").read_text(encoding="utf-8")


class Element:
    """A parsed element: its tag, attributes, ancestry and text."""

    __slots__ = ("attrs", "parents", "tag", "text")

    def __init__(self, tag: str, attrs: dict[str, str], parents: tuple[str, ...]) -> None:
        self.tag = tag
        self.attrs = attrs
        self.parents = parents
        self.text = ""

    def get(self, name: str, default: str | None = None) -> str | None:
        return self.attrs.get(name, default)


class _Collector(HTMLParser):
    """Flattens the document into elements, keeping each one's ancestry.

    HTML is not XML, so an XML parser rejects perfectly valid markup. The
    standard library's HTML parser is the right tool and needs no dependency.
    """

    VOID = frozenset(
        [
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        ]
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[Element] = []
        self._stack: list[Element] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element = Element(
            tag,
            {key: (value or "") for key, value in attrs},
            tuple(parent.tag for parent in self._stack),
        )
        self.elements.append(element)
        if tag not in self.VOID:
            self._stack.append(element)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID and self._stack:
            self._stack.pop()

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if self._stack:
            self._stack[-1].text += data


@pytest.fixture(scope="module")
def document(html: str) -> list[Element]:
    """Every element on the page, in document order."""
    collector = _Collector()
    collector.feed(html)
    assert collector.elements, "the page parsed to nothing"
    return collector.elements


def find(document: list[Element], tag: str, **attrs: str) -> Element | None:
    for element in document:
        if element.tag != tag:
            continue
        if all(element.get(key) == value for key, value in attrs.items()):
            return element
    return None


class TestMarkup:
    def test_the_page_parses(self, document: list[Element]) -> None:
        assert find(document, "html") is not None
        assert find(document, "main", id="main") is not None

    def test_the_document_declares_its_language(self, html: str) -> None:
        assert 'lang="en"' in html

    def test_there_is_exactly_one_top_level_heading(self, document: list[Element]) -> None:
        assert len([e for e in document if e.tag == "h1"]) == 1

    def test_heading_levels_do_not_skip(self, document: list[Element]) -> None:
        """The same rule the auditor applies to PDFs, applied to this page."""
        levels = [int(e.tag[1]) for e in document if re.fullmatch(r"h[1-6]", e.tag)]
        assert levels, "the page has no headings"
        assert levels[0] == 1
        for previous, current in pairwise(levels):
            assert current <= previous + 1, f"h{previous} is followed by h{current}"

    def test_there_is_a_skip_link_to_the_main_content(self, document: list[Element]) -> None:
        skip = find(document, "a", **{"class": "skip-link"})
        assert skip is not None
        assert skip.get("href") == "#main"

    def test_every_form_control_has_a_label(self, document: list[Element]) -> None:
        labelled_ids = {e.get("for") for e in document if e.tag == "label"}
        for control in document:
            if control.tag not in ("input", "select", "textarea"):
                continue
            if control.get("type") in ("hidden", "submit", "button"):
                continue
            named = (
                control.get("aria-label")
                or control.get("aria-labelledby")
                or control.get("id") in labelled_ids
                # A control inside its own label is labelled by it.
                or "label" in control.parents
            )
            assert named, f"unlabelled control: {control.get('id') or control.get('name')}"

    def test_the_radio_group_is_a_fieldset_with_a_legend(self, document: list[Element]) -> None:
        """Radio buttons without a group name are announced without their question."""
        assert find(document, "fieldset") is not None
        legend = find(document, "legend")
        assert legend is not None and "fieldset" in legend.parents
        for control in document:
            if control.get("type") == "radio":
                assert "fieldset" in control.parents

    def test_decorative_graphics_are_hidden_from_assistive_technology(
        self, document: list[Element]
    ) -> None:
        titled = {e for e in document if e.tag == "title" and "svg" in e.parents}
        for svg in [e for e in document if e.tag == "svg"]:
            assert svg.get("aria-hidden") == "true" or titled

    def test_navigation_landmarks_are_named(self, document: list[Element]) -> None:
        navs = [e for e in document if e.tag == "nav"]
        assert navs
        for nav in navs:
            assert nav.get("aria-label") or nav.get("aria-labelledby")

    def test_status_regions_are_announced(self, html: str) -> None:
        """Progress has to reach a screen reader, not only the screen."""
        assert 'role="status"' in html
        assert 'aria-live="polite"' in html
        assert 'role="log"' in html

    def test_the_element_that_receives_focus_can_be_focused(self, html: str) -> None:
        """The report heading is focused when results arrive, so it needs tabindex."""
        assert re.search(r'<h2 id="report-heading" tabindex="-1"', html)

    def test_external_links_set_noopener(self, document: list[Element]) -> None:
        for anchor in [e for e in document if e.tag == "a"]:
            href = anchor.get("href", "")
            if href.startswith("http"):
                assert "noopener" in (anchor.get("rel") or "")


class TestContentSecurityPolicy:
    def test_the_page_uses_no_inline_styles(self, html: str) -> None:
        """The policy the server sends forbids them, so the page must not need them."""
        assert not re.search(r'\sstyle="', html)

    def test_the_page_uses_no_inline_executable_script(self, html: str) -> None:
        for attributes in re.findall(r"<script([^>]*)>", html):
            assert "src=" in attributes or 'type="application/ld+json"' in attributes

    def test_no_asset_is_loaded_from_a_third_party(self, html: str) -> None:
        """A webfont from a CDN is a render-blocking request that also hands the
        visitor's address to someone else."""
        assets = re.findall(r'(?:src|href)="(https?://[^"]+)"', html)
        for asset in assets:
            assert not asset.endswith((".css", ".js", ".woff", ".woff2", ".ttf")), asset

    def test_the_static_host_sends_the_same_policy_as_the_api(self) -> None:
        headers = (WEB / "_headers").read_text(encoding="utf-8")
        assert "Content-Security-Policy" in headers
        assert "object-src 'none'" in headers
        assert "frame-ancestors 'none'" in headers

    def test_the_policy_permits_the_api_origin_the_page_calls(self, script: str) -> None:
        headers = (WEB / "_headers").read_text(encoding="utf-8")
        origin = re.search(r"'(https://[^']+onrender\.com)'", script)
        assert origin, "the script no longer names a remote API origin"
        assert origin.group(1) in headers, "connect-src would block the API the page calls"


class TestDiscoverability:
    def test_the_title_and_description_are_present_and_useful(self, html: str) -> None:
        title = re.search(r"<title>(.*?)</title>", html, re.S)
        assert title and 40 < len(title.group(1).strip()) < 70
        description = re.search(r'name="description"\s+content="(.*?)"', html, re.S)
        assert description and 70 < len(description.group(1)) < 320

    def test_a_canonical_url_is_declared(self, html: str) -> None:
        assert re.search(r'rel="canonical"\s+href="https://', html)

    @pytest.mark.parametrize(
        "property_name", ["og:title", "og:description", "og:image", "og:url", "og:type"]
    )
    def test_sharing_metadata_is_complete(self, html: str, property_name: str) -> None:
        assert f'property="{property_name}"' in html

    def test_the_social_image_exists_at_the_expected_size(self) -> None:
        from PIL import Image

        card = WEB / "social-card.png"
        assert card.is_file(), "the page references a social card that is not committed"
        with Image.open(card) as image:
            assert image.size == (1200, 630)

    def test_the_social_image_has_alternative_text(self, html: str) -> None:
        assert 'property="og:image:alt"' in html

    def test_structured_data_is_valid_json(self, html: str) -> None:
        block = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
        assert block
        data = json.loads(block.group(1))
        types = {entry["@type"] for entry in data["@graph"]}
        assert {"SoftwareApplication", "FAQPage"} <= types

    def test_the_structured_data_does_not_overstate_what_the_tool_does(self, html: str) -> None:
        """The answers a search engine may surface have to be the honest ones."""
        block = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
        faq = next(e for e in json.loads(block.group(1))["@graph"] if e["@type"] == "FAQPage")
        answers = " ".join(q["acceptedAnswer"]["text"] for q in faq["mainEntity"])
        assert "87" in answers and "136" in answers, "the coverage limit should be stated"

    def test_robots_and_sitemap_agree(self) -> None:
        robots = (WEB / "robots.txt").read_text(encoding="utf-8")
        sitemap = (WEB / "sitemap.xml").read_text(encoding="utf-8")
        location = re.search(r"Sitemap:\s*(\S+)", robots)
        assert location
        ET.fromstring(sitemap)
        assert "ada-pdf-remediator" in location.group(1)

    def test_per_upload_endpoints_are_not_offered_for_indexing(self) -> None:
        assert "Disallow: /api/" in (WEB / "robots.txt").read_text(encoding="utf-8")


class TestStyles:
    def test_reduced_motion_is_honoured(self, css: str) -> None:
        assert "prefers-reduced-motion: reduce" in css

    def test_both_colour_schemes_are_supported(self, css: str) -> None:
        assert "color-scheme: light dark" in css
        assert "prefers-color-scheme: dark" in css

    def test_focus_is_visible(self, css: str) -> None:
        assert ":focus-visible" in css
        assert "outline:" in css

    def test_no_outline_is_removed_without_replacement(self, css: str) -> None:
        for match in re.finditer(r"outline:\s*(none|0)\b", css):
            window = css[max(0, match.start() - 400) : match.end() + 400]
            assert "outline:" in window.replace(match.group(0), ""), (
                "focus outline removed with no visible replacement"
            )

    def test_the_severity_of_a_finding_is_not_carried_by_colour_alone(
        self, css: str, script: str
    ) -> None:
        """Required by WCAG 1.4.1, and doubly so for a tool about accessibility.

        Each severity gets a distinct glyph in CSS and a written word from the
        script, so the meaning survives greyscale and colour vision differences.
        """
        for severity in ("error", "warning", "review"):
            assert f"[data-severity='{severity}'] .finding__severity::before" in css
        assert "SEVERITY_LABEL" in script

    def test_headings_use_a_fixed_scale_rather_than_viewport_units(self, css: str) -> None:
        """Product UI is read at a consistent size; a heading that shrinks with
        the viewport looks worse, not better."""
        assert "clamp(" not in css

    def test_the_palette_passes_its_own_contrast_engine(self, css: str) -> None:
        """The interface is graded by the same code that grades documents.

        This caught a real failure during development: the finding metadata
        colour measured 4.27:1, under the 4.5:1 small text requires.
        """
        coloraide = pytest.importorskip("coloraide")
        from remediator.contrast import Rgb, contrast_ratio

        def table(block: str) -> dict[str, str]:
            return dict(re.findall(r"--([\w-]+):\s*(oklch\([^)]*\))", block))

        light = table(css.split(":root {")[1].split("\n}")[0])
        dark = {
            **light,
            **table(css.split("@media (prefers-color-scheme: dark) {")[1].split("\n  }")[0]),
        }

        def colour(value: str) -> Rgb:
            converted = coloraide.Color(value).convert("srgb")
            return Rgb(*[max(0.0, min(1.0, channel)) for channel in converted[:3]])

        pairs = [
            ("ink", "canvas"),
            ("ink", "surface"),
            ("ink-soft", "surface"),
            ("ink-soft", "surface-sunk"),
            ("ink-faint", "surface"),
            ("ink-faint", "surface-sunk"),
            ("accent", "surface"),
            ("on-accent", "accent"),
            ("danger", "danger-soft"),
            ("warn", "warn-soft"),
            ("info", "info-soft"),
            ("good", "good-soft"),
        ]
        for scheme, tokens in (("light", light), ("dark", dark)):
            for foreground, background in pairs:
                ratio = contrast_ratio(colour(tokens[foreground]), colour(tokens[background]))
                assert ratio >= 4.5, (
                    f"{scheme}: {foreground} on {background} is {ratio:.2f}:1, "
                    "below the 4.5:1 small text requires"
                )


class TestBehaviourIsDataDriven:
    def test_the_report_is_rendered_from_the_response(self, script: str) -> None:
        """The previous interface hardcoded a scorecard reading '100% COMPLIANT'
        regardless of what the audit returned."""
        assert "job.result?.audit" in script
        assert "renderFindings" in script
        assert "renderTally" in script

    def test_no_hardcoded_verdict_survives_in_the_markup(self, html: str) -> None:
        lowered = html.lower()
        assert "100% compliant" not in lowered
        assert "✓" not in html, "a static tick would assert a result the audit has not given"

    def test_progress_comes_from_the_event_stream(self, script: str) -> None:
        assert "EventSource" in script
        assert "addEventListener('progress'" in script

    def test_progress_is_not_animated_on_a_timer(self, script: str) -> None:
        """The old interface advanced its stepper on setTimeout at fixed delays,
        describing work that was not happening."""
        code = re.sub(r"/\*.*?\*/|//[^\n]*", "", script, flags=re.S)
        assert "setTimeout(" not in code
        assert "setInterval(" not in code

    def test_the_stages_shown_match_the_stages_the_pipeline_reports(self, script: str) -> None:
        from remediator.progress import Stage

        block = re.search(r"const STAGES = \[(.*?)\];", script, re.S)
        assert block, "the interface no longer declares a stage list"
        declared = set(re.findall(r"\['([a-z-]+)',", block.group(1)))
        known = {stage.value for stage in Stage}
        assert declared, "no stages are declared in the interface"
        assert declared <= known, f"the interface invents stages: {sorted(declared - known)}"

    def test_failures_are_surfaced_in_the_page_not_in_an_alert(self, script: str) -> None:
        """A browser alert cannot be styled, translated or read in context."""
        assert "alert(" not in script
        assert "function fail(" in script

    def test_the_endpoints_called_are_the_ones_the_service_exposes(self, script: str) -> None:
        """Every path the script builds must be a route the service serves."""
        from remediator.service import create_app

        called = set(re.findall(r"\$\{API_BASE\}(/[\w/$\{\}.]*)", script))
        assert called, "the script calls no API endpoints"

        app = create_app(workspace=None, enable_sweeper=False)
        served = {str(rule) for rule in app.url_map.iter_rules()}
        for path in called:
            normalised = re.sub(r"\$\{[^}]+\}", "<job_id>", path)
            assert normalised in served, f"the interface calls {normalised}, which is not routed"
