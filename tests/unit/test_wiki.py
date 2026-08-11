"""Tests for the pure wiki_to_md converter.

Every row of the conversion table gets a case, plus the edge cases from
the test strategy: nested lists, tables with mono/links, pseudo-markup
inside code blocks, unbalanced panels, and non-ASCII content.
"""

import logging

import pytest

from jira2md.markup.wiki import (
    reset_macro_warnings,
    wiki_to_md,
)


@pytest.fixture(autouse=True)
def _clean_macro_warnings():
    reset_macro_warnings()
    yield
    reset_macro_warnings()


class TestHeadings:
    @pytest.mark.parametrize(
        ("level", "prefix"),
        [(1, "#"), (2, "##"), (3, "###"), (4, "####"), (5, "#####"), (6, "######")],
    )
    def test_heading_levels(self, level: int, prefix: str) -> None:
        assert wiki_to_md(f"h{level}. Title") == f"{prefix} Title"


class TestInlineFormatting:
    def test_bold(self) -> None:
        assert wiki_to_md("some *text* here") == "some **text** here"

    def test_italic(self) -> None:
        assert wiki_to_md("some _text_ here") == "some *text* here"

    def test_strikethrough(self) -> None:
        assert wiki_to_md("this is -gone- now") == "this is ~~gone~~ now"

    def test_strikethrough_leaves_dates_alone(self) -> None:
        assert wiki_to_md("released 2024-01-15 ok") == "released 2024-01-15 ok"

    def test_underline(self) -> None:
        assert wiki_to_md("+inserted+") == "<u>inserted</u>"

    def test_superscript(self) -> None:
        assert wiki_to_md("x^2^") == "x<sup>2</sup>"

    def test_subscript(self) -> None:
        assert wiki_to_md("H~2~O") == "H<sub>2</sub>O"

    def test_inline_mono(self) -> None:
        assert wiki_to_md("call {{get_user()}} now") == "call `get_user()` now"


class TestCodeBlocks:
    def test_code_with_language(self) -> None:
        result = wiki_to_md("{code:java}int x = 1;{code}")
        assert result == "```java\nint x = 1;\n```"

    def test_noformat(self) -> None:
        result = wiki_to_md("{noformat}raw  *text*{noformat}")
        assert result == "```\nraw  *text*\n```"

    def test_code_block_inner_markup_untouched(self) -> None:
        source = "{code}h1. not a heading\n*not bold*\n|not|table|{code}"
        result = wiki_to_md(source)
        assert "h1. not a heading" in result
        assert "*not bold*" in result
        assert "|not|table|" in result
        assert result.startswith("```")

    def test_inline_mono_inner_markup_untouched(self) -> None:
        assert wiki_to_md("{{*not bold*}}") == "`*not bold*`"


class TestQuotesAndPanels:
    def test_quote_block(self) -> None:
        result = wiki_to_md("{quote}line one\nline two{quote}")
        assert result == "> line one\n> line two"

    def test_bq_prefix(self) -> None:
        assert wiki_to_md("bq. quoted line").startswith("> quoted line")

    def test_panel_with_title_blockquote(self) -> None:
        result = wiki_to_md("{panel:title=Warning}careful{panel}")
        assert "> **Warning**" in result
        assert "> careful" in result

    def test_panel_without_title(self) -> None:
        result = wiki_to_md("{panel}body text{panel}")
        assert "> body text" in result

    def test_unbalanced_panel_emitted_as_is(self) -> None:
        source = "{panel:title=Broken}no closing tag"
        result = wiki_to_md(source)
        assert "{panel:title=Broken}" in result


class TestLists:
    def test_nested_lists_three_deep(self) -> None:
        source = "* one\n** two\n*** three"
        result = wiki_to_md(source)
        assert "- one" in result
        assert "  - two" in result
        assert "    - three" in result

    def test_ordered_lists(self) -> None:
        source = "# first\n## second"
        result = wiki_to_md(source)
        assert "1. first" in result
        assert "  1. second" in result

    def test_mixed_lists(self) -> None:
        result = wiki_to_md("*# nested ordered under bullet")
        assert result == "  1. nested ordered under bullet"


class TestTables:
    def test_header_and_rows(self) -> None:
        source = "||h1||h2||\n|c1|c2|"
        result = wiki_to_md(source)
        lines = result.split("\n")
        assert lines[0] == "|h1|h2|"
        assert lines[1] == "|---|---|"
        assert lines[2] == "|c1|c2|"

    def test_table_with_mono_and_links(self) -> None:
        source = "||cmd||site||\n|{{run.sh}}|[home|https://example.com]|"
        result = wiki_to_md(source)
        assert "`run.sh`" in result
        assert "[home](https://example.com)" in result
        assert "|---|---|" in result


class TestLinksAndMentions:
    def test_link_with_text(self) -> None:
        assert wiki_to_md("[docs|https://example.com]") == "[docs](https://example.com)"

    def test_bare_link(self) -> None:
        result = wiki_to_md("[https://example.com] end")
        assert "https://example.com" in result
        assert "[" not in result.replace(r"\[", "")

    def test_relative_link_resolved_with_base_url(self) -> None:
        result = wiki_to_md(
            "[issue|/browse/ABC-1]", base_url="https://jira.example.com"
        )
        assert result == "[issue](https://jira.example.com/browse/ABC-1)"

    def test_mention_resolved_via_users(self) -> None:
        result = wiki_to_md(
            "ping [~accountid:abc123]", users={"abc123": "Alice Example"}
        )
        assert result == "ping @Alice Example"

    def test_mention_unknown_account_falls_back(self) -> None:
        result = wiki_to_md("ping [~accountid:abc123]")
        assert result == "ping @user_abc123"

    def test_mention_non_ascii_display_name(self) -> None:
        result = wiki_to_md(
            "[~accountid:x1]",
            users={"x1": "Zo\u00eb M\u00fcller \u2014 \u00fcnicode"},
        )
        assert result == "@Zo\u00eb M\u00fcller \u2014 \u00fcnicode"


class TestImages:
    def test_bare_image_rewritten_to_assets(self) -> None:
        assert wiki_to_md("!image.png|thumbnail!") == "![](assets/image.png)"

    def test_image_custom_assets_dir(self) -> None:
        result = wiki_to_md("!img.png!", assets_dir="files")
        assert result == "![](files/img.png)"

    def test_image_with_alt_text(self) -> None:
        result = wiki_to_md("!img.png|alt=Diagram!")
        assert result == "![Diagram](assets/img.png)"

    def test_image_absolute_url_not_rewritten(self) -> None:
        result = wiki_to_md("!https://example.com/i.png!")
        assert result == "![](https://example.com/i.png)"


class TestColorAndMacros:
    def test_color_stripped_in_extended(self) -> None:
        assert wiki_to_md("{color:#ff0000}red text{color}") == "red text"

    def test_anchor_and_toc_dropped(self) -> None:
        result = wiki_to_md("{anchor:top}text {toc}")
        assert result.strip() == "text"

    def test_unknown_macro_emitted_as_is(self) -> None:
        result = wiki_to_md("value {status} here")
        assert "{status}" in result

    def test_unknown_macro_warned_once(self, caplog) -> None:
        with caplog.at_level(logging.WARNING):
            wiki_to_md("{status} and {status}")
            wiki_to_md("{status} again")
        warnings = [
            record for record in caplog.records if "status" in record.getMessage()
        ]
        assert len(warnings) == 1


class TestStructuralRules:
    def test_horizontal_rule(self) -> None:
        assert wiki_to_md("above\n----\nbelow") == "above\n---\nbelow"

    def test_hard_line_break(self) -> None:
        result = wiki_to_md("line one\\\\\nline two")
        assert result == "line one  \nline two"


class TestPlainEscaping:
    def test_lone_star_escaped(self) -> None:
        assert wiki_to_md("2 * 3") == r"2 \* 3"

    def test_lone_underscore_escaped(self) -> None:
        assert wiki_to_md("snake_case_name") == r"snake\_case\_name"

    def test_angle_bracket_escaped(self) -> None:
        assert wiki_to_md("a < b") == r"a \< b"

    def test_backtick_escaped(self) -> None:
        assert wiki_to_md("use `raw` ticks") == r"use \`raw\` ticks"

    def test_generated_link_not_escaped(self) -> None:
        result = wiki_to_md("[docs|https://example.com]")
        assert r"\[" not in result
        assert result == "[docs](https://example.com)"

    def test_generated_tags_not_escaped(self) -> None:
        result = wiki_to_md("+inserted+")
        assert "<u>inserted</u>" in result


class TestConservativeMode:
    """extended=False keeps markup the full rule table would transform."""

    def test_underline_uses_ins_tag(self) -> None:
        assert wiki_to_md("+inserted+", extended=False) == "<ins>inserted</ins>"

    def test_color_becomes_span(self) -> None:
        # The replacement template emits backslash-escaped quotes, so
        # they are part of the expected output rather than an artefact.
        result = wiki_to_md("{color:red}x{color}", extended=False)
        assert result == r"<span style=\"color:red\">x</span>"

    def test_strikethrough_untouched(self) -> None:
        assert wiki_to_md("a -b- c", extended=False) == "a -b- c"

    def test_no_plain_escaping(self) -> None:
        assert wiki_to_md("2 * 3", extended=False) == "2 * 3"

    def test_anchor_kept(self) -> None:
        assert wiki_to_md("{anchor:x}t", extended=False) == "{anchor:x}t"

    def test_image_not_rewritten(self) -> None:
        assert wiki_to_md("!img.png!", extended=False) == "![](img.png)"

    def test_panel_keeps_bold_title(self) -> None:
        result = wiki_to_md("{panel:title=T}body{panel}", extended=False)
        assert "**T**" in result
        assert ">" not in result

    def test_composite_document(self) -> None:
        # One document exercising every construct at once, so the
        # conservative mode cannot drift a rule at a time.
        source = (
            "h2. Title\n*bold* _italic_ {{mono}}\n"
            "{code:python}print('*x*'){code}\n"
            "||a||b||\n|1|2|\n[link|https://example.com]"
        )
        result = wiki_to_md(source, extended=False)
        assert "## Title" in result
        assert "**bold** *italic* `mono`" in result
        assert "```python\nprint('*x*')\n```" in result
        assert "[link](https://example.com)" in result

    def test_empty_input(self) -> None:
        assert wiki_to_md("") == ""
