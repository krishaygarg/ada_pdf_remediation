"""Tests for font character mapping recovery.

The governing principle under test is that an unresolvable code is omitted
rather than guessed. A missing character is visible to the reader; a wrong one
is not.
"""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from remediator.fonts.embedded import type1_builtin_encoding
from remediator.fonts.encodings import apply_differences, encoding_table
from remediator.fonts.glyphnames import (
    normalise_for_text_extraction,
    resolve_glyph_name,
)
from remediator.fonts.recovery import (
    SOURCE_PRIORITY,
    RecoveredMapping,
    Source,
    recover_mapping,
)
from remediator.fonts.tounicode import (
    build_tounicode_cmap,
    choose_codespace,
    parse_tounicode_cmap,
)


class TestGlyphNameResolution:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("A", "A"),
            ("space", " "),
            ("endash", "–"),
            ("emdash", "—"),
            ("bullet", "•"),
            ("Delta", "∆"),
            ("minus", "−"),
            ("alpha", "α"),
            ("degree", "°"),
        ],
    )
    def test_adobe_glyph_list_names(self, name: str, expected: str) -> None:
        assert resolve_glyph_name(name) == expected

    @pytest.mark.parametrize(
        ("name", "expected"),
        [("uni0041", "A"), ("uni00E9", "é"), ("uni03B1", "α"), ("uni00660066", "ff")],
    )
    def test_uni_convention(self, name: str, expected: str) -> None:
        assert resolve_glyph_name(name) == expected

    @pytest.mark.parametrize(("name", "expected"), [("u0041", "A"), ("u1F600", "😀")])
    def test_u_convention(self, name: str, expected: str) -> None:
        assert resolve_glyph_name(name) == expected

    def test_surrogate_code_points_are_refused(self) -> None:
        """A lone surrogate is not a character and cannot be encoded as text."""
        assert resolve_glyph_name("uD800") is None

    @pytest.mark.parametrize("name", ["g42", "cid1234", "glyph7", "index12", "G99"])
    def test_index_based_names_resolve_to_nothing(self, name: str) -> None:
        """An index identifies a glyph slot and says nothing about meaning.

        Returning a guess here is how text becomes wrong rather than missing.
        """
        assert resolve_glyph_name(name) is None

    @pytest.mark.parametrize(("name", "expected"), [("fi", "fi"), ("ffl", "ffl"), ("ff", "ff")])
    def test_ligatures_decompose_to_their_letters(self, name: str, expected: str) -> None:
        """Extracting 'fi' keeps the word findable; U+FB01 does not."""
        assert resolve_glyph_name(name) == expected

    def test_underscore_joined_composites(self) -> None:
        assert resolve_glyph_name("f_f_i") == "ffi"

    def test_variant_suffixes_fall_back_to_the_base_glyph(self) -> None:
        assert resolve_glyph_name("a.sc") == "a"
        assert resolve_glyph_name("one.oldstyle") == "1"

    def test_tex_names_absent_from_the_adobe_list(self) -> None:
        assert resolve_glyph_name("lscript") == "ℓ"
        assert resolve_glyph_name("epsilon1") == "ε"

    @pytest.mark.parametrize("name", ["", "notaglyphname", "zzz999zzz"])
    def test_unknown_names_resolve_to_nothing(self, name: str) -> None:
        assert resolve_glyph_name(name) is None

    def test_a_leading_slash_is_tolerated(self) -> None:
        assert resolve_glyph_name("/endash") == "–"

    def test_normalisation_decomposes_presentation_forms(self) -> None:
        assert normalise_for_text_extraction("ﬁle") == "file"
        assert normalise_for_text_extraction("plain") == "plain"


class TestEncodingTables:
    @pytest.mark.parametrize(
        "name", ["StandardEncoding", "WinAnsiEncoding", "MacRomanEncoding", "PDFDocEncoding"]
    )
    def test_predefined_tables_are_populated(self, name: str) -> None:
        table = encoding_table(name)
        assert len(table) > 100
        assert table[65] == "A"

    def test_standard_encoding_is_not_latin_one(self) -> None:
        """Treating StandardEncoding as Latin-1 mistranslates punctuation.

        Code 0xB7 is 'bullet' in StandardEncoding and 'middle dot' in Latin-1.
        """
        assert encoding_table("StandardEncoding")[0xB7] == "bullet"

    def test_an_unknown_encoding_yields_an_empty_table(self) -> None:
        assert encoding_table("MadeUpEncoding") == {}

    def test_differences_override_the_base(self) -> None:
        base = {65: "A", 66: "B"}
        result = apply_differences(base, [65, "/alpha"])
        assert result[65] == "alpha"
        assert result[66] == "B"

    def test_differences_advance_the_code_for_each_name(self) -> None:
        result = apply_differences({}, [10, "/a", "/b", "/c", 20, "/z"])
        assert result == {10: "a", 11: "b", 12: "c", 20: "z"}

    def test_malformed_entries_are_skipped_rather_than_fatal(self) -> None:
        result = apply_differences({}, [1, "/a", None, "/b"])
        assert result[1] == "a"


class TestType1BuiltinEncoding:
    def test_entries_are_read_from_the_cleartext_portion(self) -> None:
        program = b"""%!PS-AdobeFont-1.0
/Encoding 256 array
0 1 255 {1 index exch /.notdef put} for
dup 1 /Delta put
dup 123 /endash put
dup 15 /bullet put
readonly def
eexec
"""
        table = type1_builtin_encoding(program, len(program))
        assert table == {1: "Delta", 123: "endash", 15: "bullet"}

    def test_a_named_encoding_is_expanded(self) -> None:
        program = b"%!PS-AdobeFont-1.0\n/Encoding StandardEncoding def\neexec\n"
        table = type1_builtin_encoding(program, len(program))
        assert table[65] == "A"

    def test_codes_outside_a_byte_are_ignored(self) -> None:
        program = b"dup 300 /bogus put dup 7 /alpha put"
        assert type1_builtin_encoding(program) == {7: "alpha"}

    def test_an_empty_program_yields_nothing(self) -> None:
        assert type1_builtin_encoding(b"") == {}

    @pytest.mark.slow
    def test_the_real_sample_fonts_are_readable(self, sample_pdf: Path) -> None:
        """The bundled document's fonts declare no /Encoding in the PDF at all.

        Their mapping exists only inside the embedded program, which is exactly
        the case that previously forced a guess.
        """
        from remediator.fonts.embedded import extract_builtin_encoding

        with pikepdf.open(sample_pdf) as pdf:
            tables = []
            for page in pdf.pages:
                fonts = (page.obj.get("/Resources") or {}).get("/Font")
                if not fonts:
                    continue
                for _name, font in fonts.items():
                    table = extract_builtin_encoding(font)
                    if table:
                        tables.append((str(font.get("/BaseFont")), table))

        assert tables, "no built-in encoding could be read from the sample"
        combined = dict(tables)
        cmr12 = next(table for name, table in combined.items() if "CMR12" in name)
        assert cmr12[123] == "endash"
        assert cmr12[1] == "Delta"


class TestCodespaceSelection:
    def test_a_simple_font_with_byte_codes_uses_one_byte(self) -> None:
        assert choose_codespace([0, 65, 255], composite=False).byte_width == 1

    def test_a_code_above_255_forces_two_bytes(self) -> None:
        assert choose_codespace([0, 300], composite=False).byte_width == 2

    def test_a_composite_font_always_uses_two_bytes(self) -> None:
        """A Type 0 font is addressed through a two byte CMap.

        The previous implementation padded the mapping to 256 entries before
        measuring, which pinned every font to a one byte codespace and produced
        an inapplicable map for composite fonts.
        """
        assert choose_codespace([0, 1, 2], composite=True).byte_width == 2

    def test_the_declaration_matches_the_width(self) -> None:
        assert choose_codespace([1], composite=False).declaration == "<00> <FF>"
        assert choose_codespace([1], composite=True).declaration == "<0000> <FFFF>"


class TestCMapGeneration:
    def test_a_generated_map_round_trips(self) -> None:
        mapping = {1: "∆", 65: "A", 123: "–", 200: "ff"}
        parsed = parse_tounicode_cmap(build_tounicode_cmap(mapping).encode("utf-8"))
        assert parsed == mapping

    def test_contiguous_runs_are_emitted_as_ranges(self) -> None:
        """Compaction keeps the stream small; it is parsed on every extraction."""
        mapping = {code: chr(ord("a") + code - 97) for code in range(97, 123)}
        cmap = build_tounicode_cmap(mapping)
        assert "beginbfrange" in cmap
        assert parse_tounicode_cmap(cmap.encode("utf-8")) == mapping

    def test_a_compacted_map_is_shorter_than_one_entry_per_code(self) -> None:
        mapping = {code: chr(code) for code in range(32, 127)}
        cmap = build_tounicode_cmap(mapping)
        assert cmap.count("\n") < len(mapping)

    def test_multi_character_values_are_not_folded_into_a_range(self) -> None:
        mapping = {10: "ff", 11: "fi", 12: "fl"}
        assert parse_tounicode_cmap(build_tounicode_cmap(mapping).encode("utf-8")) == mapping

    def test_blocks_respect_the_hundred_entry_limit(self) -> None:
        mapping = {code: chr(0x4E00 + code * 7) for code in range(250)}
        cmap = build_tounicode_cmap(mapping)
        for block in cmap.split("beginbfchar")[1:]:
            declared = block.split("endbfchar")[0]
            assert declared.count("<") // 2 <= 100

    def test_an_empty_mapping_still_produces_a_valid_program(self) -> None:
        cmap = build_tounicode_cmap({})
        assert "begincmap" in cmap
        assert "endcmap" in cmap
        assert parse_tounicode_cmap(cmap.encode("utf-8")) == {}

    def test_the_font_name_is_sanitised(self) -> None:
        cmap = build_tounicode_cmap({65: "A"}, font_name="ABCDEF+Weird Name/1")
        assert "/ABCDEFWeirdName1-UCS2" in cmap

    @given(
        st.dictionaries(
            st.integers(min_value=0, max_value=0xFFFF),
            st.text(
                alphabet=st.characters(min_codepoint=32, max_codepoint=0x2FFF),
                min_size=1,
                max_size=3,
            ),
            min_size=0,
            max_size=120,
        )
    )
    @settings(max_examples=60, deadline=None)
    def test_arbitrary_mappings_round_trip(self, mapping: dict[int, str]) -> None:
        composite = bool(mapping) and max(mapping) > 0xFF
        cmap = build_tounicode_cmap(mapping, composite=composite)
        assert parse_tounicode_cmap(cmap.encode("utf-8")) == mapping


class TestCMapParsing:
    def test_a_bfrange_triple_is_not_also_read_as_a_bfchar_pair(self) -> None:
        """Regression for a parser that applied both patterns to the whole stream.

        A pattern for '<hex> <hex>' also matches the first two elements of a
        '<hex> <hex> <hex>' range, so every range was additionally recorded as
        a single character with the wrong destination.
        """
        cmap = b"begincmap\n1 beginbfrange\n<0041> <0043> <0061>\nendbfrange\nendcmap"
        assert parse_tounicode_cmap(cmap) == {0x41: "a", 0x42: "b", 0x43: "c"}

    def test_array_form_ranges_are_supported(self) -> None:
        cmap = (
            b"begincmap\n1 beginbfrange\n<0001> <0003> [<0041> <0042> <0043>]\nendbfrange\nendcmap"
        )
        assert parse_tounicode_cmap(cmap) == {1: "A", 2: "B", 3: "C"}

    def test_both_block_kinds_can_appear_together(self) -> None:
        cmap = (
            b"begincmap\n"
            b"1 beginbfchar\n<0A> <0058>\nendbfchar\n"
            b"1 beginbfrange\n<10> <12> <0061>\nendbfrange\n"
            b"endcmap"
        )
        assert parse_tounicode_cmap(cmap) == {0x0A: "X", 0x10: "a", 0x11: "b", 0x12: "c"}

    def test_a_reversed_range_is_ignored(self) -> None:
        cmap = b"begincmap\n1 beginbfrange\n<0043> <0041> <0061>\nendbfrange\nendcmap"
        assert parse_tounicode_cmap(cmap) == {}

    def test_unparseable_input_yields_nothing_rather_than_raising(self) -> None:
        assert parse_tounicode_cmap(b"\x00\x01 not a cmap") == {}


class TestRecoveryPriority:
    def _font(self, pdf: pikepdf.Pdf, **entries) -> pikepdf.Object:
        base = pikepdf.Dictionary(
            Type=pikepdf.Name("/Font"),
            Subtype=pikepdf.Name("/Type1"),
            BaseFont=pikepdf.Name("/Test"),
        )
        for key, value in entries.items():
            base[f"/{key}"] = value
        return pdf.make_indirect(base)

    def test_the_priority_order_matches_the_enum_it_documents(self) -> None:
        """SOURCE_PRIORITY used to be a second, hand-written ordering that
        nothing compared against the enum, so the two could disagree silently.
        It is derived now, and this pins that it stays derived."""
        assert tuple(Source) == SOURCE_PRIORITY
        assert SOURCE_PRIORITY[0] is Source.EXISTING_TOUNICODE
        assert SOURCE_PRIORITY[-1] is Source.BASE_ENCODING

    def test_counts_are_reported_most_authoritative_source_first(self) -> None:
        """Insertion order would report whichever source happened to resolve a
        code first, which varies with the document rather than the authority."""
        mapping = RecoveredMapping(font_name="Test", composite=False)
        # Added least-authoritative first, so insertion order is the reverse of
        # the order the report has to use.
        mapping.add(1, "a", Source.BASE_ENCODING)
        mapping.add(2, "b", Source.EMBEDDED_PROGRAM)
        mapping.add(3, "c", Source.EXISTING_TOUNICODE)
        reported = list(mapping.counts_by_source())
        assert reported == [
            Source.EXISTING_TOUNICODE.value,
            Source.EMBEDDED_PROGRAM.value,
            Source.BASE_ENCODING.value,
        ]

    def test_a_source_that_resolved_nothing_is_omitted(self) -> None:
        mapping = RecoveredMapping(font_name="Test", composite=False)
        mapping.add(1, "a", Source.EMBEDDED_PROGRAM)
        assert mapping.counts_by_source() == {Source.EMBEDDED_PROGRAM.value: 1}

    def test_an_existing_map_takes_precedence(self) -> None:
        pdf = pikepdf.new()
        cmap = build_tounicode_cmap({65: "Z"})
        font = self._font(
            pdf,
            ToUnicode=pikepdf.Stream(pdf, cmap.encode("ascii")),
            Encoding=pikepdf.Name("/WinAnsiEncoding"),
        )
        recovered = recover_mapping(font)
        assert recovered.mapping[65] == "Z"
        assert recovered.provenance[65] is Source.EXISTING_TOUNICODE

    def test_differences_override_the_base_encoding(self) -> None:
        pdf = pikepdf.new()
        font = self._font(
            pdf,
            Encoding=pikepdf.Dictionary(
                BaseEncoding=pikepdf.Name("/WinAnsiEncoding"),
                Differences=pikepdf.Array([65, pikepdf.Name("/alpha")]),
            ),
        )
        recovered = recover_mapping(font)
        assert recovered.mapping[65] == "α"
        assert recovered.provenance[65] is Source.ENCODING_DIFFERENCES

    def test_a_symbolic_font_is_not_given_a_text_encoding(self) -> None:
        """Guessing StandardEncoding for a symbolic font is what corrupted text.

        A symbolic font's codes address glyphs unrelated to Latin letters, so a
        font with no other source of information must yield nothing rather than
        a plausible-looking wrong answer.
        """
        pdf = pikepdf.new()
        font = self._font(
            pdf,
            FontDescriptor=pikepdf.Dictionary(Flags=pikepdf.Integer(4)),
        )
        assert recover_mapping(font).mapping == {}

    def test_a_nonsymbolic_font_falls_back_to_standard_encoding(self) -> None:
        pdf = pikepdf.new()
        font = self._font(pdf, FontDescriptor=pikepdf.Dictionary(Flags=pikepdf.Integer(32)))
        recovered = recover_mapping(font)
        assert recovered.mapping[65] == "A"
        assert recovered.provenance[65] is Source.BASE_ENCODING

    def test_an_all_space_existing_map_is_not_treated_as_authoritative(self) -> None:
        """A map written by an earlier run of this tool carries no information."""
        pdf = pikepdf.new()
        cmap = build_tounicode_cmap(dict.fromkeys(range(32, 128), " "))
        font = self._font(
            pdf,
            ToUnicode=pikepdf.Stream(pdf, cmap.encode("ascii")),
            Encoding=pikepdf.Name("/WinAnsiEncoding"),
        )
        recovered = recover_mapping(font)
        assert recovered.mapping[65] == "A"

    def test_unresolvable_glyph_names_are_recorded_not_invented(self) -> None:
        pdf = pikepdf.new()
        font = self._font(
            pdf,
            FontDescriptor=pikepdf.Dictionary(Flags=pikepdf.Integer(4)),
            Encoding=pikepdf.Dictionary(
                Differences=pikepdf.Array([7, pikepdf.Name("/madeupglyphname")])
            ),
        )
        recovered = recover_mapping(font)
        assert 7 not in recovered.mapping
        assert recovered.unresolved_glyphs[7] == "madeupglyphname"

    def test_a_composite_font_is_marked_as_such(self) -> None:
        pdf = pikepdf.new()
        font = pdf.make_indirect(
            pikepdf.Dictionary(
                Type=pikepdf.Name("/Font"),
                Subtype=pikepdf.Name("/Type0"),
                BaseFont=pikepdf.Name("/Composite"),
                Encoding=pikepdf.Name("/Identity-H"),
            )
        )
        recovered = recover_mapping(font)
        assert recovered.composite
        assert "<0000> <FFFF>" in recovered.to_cmap()


@pytest.fixture(scope="module")
def texts(tmp_path_factory: pytest.TempPathFactory) -> tuple[str, str]:
    """Extracted text of the bundled sample, before and after remediation."""
    fitz = pytest.importorskip("fitz")
    from remediator.pipeline import remediate_single_pdf

    source = Path("samples/physics/physics.pdf")
    if not source.exists():  # pragma: no cover - sample is committed
        pytest.skip("sample document is unavailable")
    target = tmp_path_factory.mktemp("fidelity") / "out.pdf"
    remediate_single_pdf(str(source), str(target))

    def extract(path: Path) -> str:
        with fitz.open(path) as doc:
            return "".join(page.get_text() for page in doc)

    return extract(source), extract(target)


@pytest.mark.slow
class TestTextFidelityOnTheRealDocument:
    """The measurement that matters: does the text survive remediation."""

    def test_the_en_dash_survives(self, texts: tuple[str, str]) -> None:
        original, output = texts
        assert original.count("–") > 0
        assert output.count("–") == original.count("–")

    def test_mathematical_operators_survive(self, texts: tuple[str, str]) -> None:
        original, output = texts
        for character in ("∆", "−"):
            assert output.count(character) == original.count(character), (
                f"{character!r} count changed from {original.count(character)} "
                f"to {output.count(character)}"
            )

    def test_list_bullets_survive(self, texts: tuple[str, str]) -> None:
        original, output = texts
        assert output.count("•") == original.count("•")

    def test_no_spurious_braces_are_introduced(self, texts: tuple[str, str]) -> None:
        """Code 123 is an en dash in Computer Modern, not an opening brace."""
        original, output = texts
        assert output.count("{") <= original.count("{")

    def test_overall_fidelity_is_high(self, texts: tuple[str, str]) -> None:
        import difflib

        original, output = texts
        ratio = difflib.SequenceMatcher(
            None, "".join(original.split()), "".join(output.split())
        ).ratio()
        assert ratio > 0.99, f"text fidelity dropped to {ratio:.2%}"

    def test_the_only_differences_are_ligature_decompositions(self, texts: tuple[str, str]) -> None:
        """Deliberate: 'fi' is searchable, U+FB01 is not."""
        import difflib

        original, output = texts
        a = "".join(original.split())
        b = "".join(output.split())
        for tag, i1, i2, _j1, _j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
            if tag == "equal":
                continue
            segment = a[i1:i2]
            assert any(0xFB00 <= ord(ch) <= 0xFB4F for ch in segment), (
                f"unexpected difference at {segment!r}"
            )
