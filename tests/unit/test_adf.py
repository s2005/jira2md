"""Tests for the ADF to Markdown walker."""

from __future__ import annotations

import logging
from typing import Any

from jira2md.markup.adf import adf_to_md


def text(value: str, marks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    node: dict[str, Any] = {"type": "text", "text": value}
    if marks:
        node["marks"] = marks
    return node


def paragraph(*children: dict[str, Any]) -> dict[str, Any]:
    return {"type": "paragraph", "content": list(children)}


def doc(*children: dict[str, Any]) -> dict[str, Any]:
    return {"type": "doc", "content": list(children)}


class TestBasicNodes:
    def test_empty_and_non_dict_input(self) -> None:
        assert adf_to_md(None) == ""
        assert adf_to_md("not adf") == ""
        assert adf_to_md({}) == ""

    def test_paragraph(self) -> None:
        assert adf_to_md(doc(paragraph(text("hello")))) == "hello"

    def test_blocks_joined_with_blank_line(self) -> None:
        result = adf_to_md(doc(paragraph(text("one")), paragraph(text("two"))))
        assert result == "one\n\ntwo"

    def test_heading_levels_clamped(self) -> None:
        heading = {
            "type": "heading",
            "attrs": {"level": 9},
            "content": [text("Deep")],
        }
        assert adf_to_md(doc(heading)) == "###### Deep"
        heading["attrs"] = {"level": 2}
        assert adf_to_md(doc(heading)) == "## Deep"

    def test_rule_and_hard_break(self) -> None:
        result = adf_to_md(
            doc(
                paragraph(text("a"), {"type": "hardBreak"}, text("b")), {"type": "rule"}
            )
        )
        assert result == "a\nb\n\n---"


class TestLists:
    def test_bullet_list(self) -> None:
        node = {
            "type": "bulletList",
            "content": [
                {"type": "listItem", "content": [paragraph(text("one"))]},
                {"type": "listItem", "content": [paragraph(text("two"))]},
            ],
        }
        assert adf_to_md(doc(node)) == "- one\n- two"

    def test_ordered_list_numbers(self) -> None:
        node = {
            "type": "orderedList",
            "content": [
                {"type": "listItem", "content": [paragraph(text("one"))]},
                {"type": "listItem", "content": [paragraph(text("two"))]},
            ],
        }
        assert adf_to_md(doc(node)) == "1. one\n2. two"

    def test_nested_list_indented(self) -> None:
        inner = {
            "type": "bulletList",
            "content": [{"type": "listItem", "content": [paragraph(text("child"))]}],
        }
        outer = {
            "type": "bulletList",
            "content": [
                {"type": "listItem", "content": [paragraph(text("parent")), inner]}
            ],
        }
        assert adf_to_md(doc(outer)) == "- parent\n  - child"


class TestCodeAndQuote:
    def test_code_block_with_language(self) -> None:
        node = {
            "type": "codeBlock",
            "attrs": {"language": "python"},
            "content": [text("print(1)")],
        }
        assert adf_to_md(doc(node)) == "```python\nprint(1)\n```"

    def test_blockquote(self) -> None:
        node = {"type": "blockquote", "content": [paragraph(text("quoted"))]}
        assert adf_to_md(doc(node)) == "> quoted"


class TestTable:
    def test_table_with_header_row(self) -> None:
        node = {
            "type": "table",
            "content": [
                {
                    "type": "tableRow",
                    "content": [
                        {"type": "tableHeader", "content": [paragraph(text("h1"))]},
                        {"type": "tableHeader", "content": [paragraph(text("h2"))]},
                    ],
                },
                {
                    "type": "tableRow",
                    "content": [
                        {"type": "tableCell", "content": [paragraph(text("a"))]},
                        {"type": "tableCell", "content": [paragraph(text("b"))]},
                    ],
                },
            ],
        }
        assert adf_to_md(doc(node)) == "| h1 | h2 |\n|---|---|\n| a | b |"

    def test_pipe_in_cell_escaped(self) -> None:
        node = {
            "type": "table",
            "content": [
                {
                    "type": "tableRow",
                    "content": [
                        {"type": "tableCell", "content": [paragraph(text("a|b"))]}
                    ],
                }
            ],
        }
        assert adf_to_md(doc(node)) == "| a\\|b |"


class TestPanelsAndStructure:
    def test_panel_with_label(self) -> None:
        node = {
            "type": "panel",
            "attrs": {"panelType": "warning"},
            "content": [paragraph(text("careful"))],
        }
        assert adf_to_md(doc(node)) == "> **Warning**\n> careful"

    def test_expand_with_title(self) -> None:
        node = {
            "type": "expand",
            "attrs": {"title": "More"},
            "content": [paragraph(text("hidden"))],
        }
        assert adf_to_md(doc(node)) == "**More**\n\nhidden"

    def test_status_and_date(self) -> None:
        status = {"type": "status", "attrs": {"text": "DONE"}}
        date = {"type": "date", "attrs": {"timestamp": "2026-01-01"}}
        assert adf_to_md(doc(paragraph(text("x")), status)) == "x\n\n**DONE**"
        assert adf_to_md(doc(paragraph(text("x "), date))) == "x 2026-01-01"


class TestMediaAndCards:
    def test_media_single_with_media(self) -> None:
        node = {
            "type": "mediaSingle",
            "content": [
                {
                    "type": "media",
                    "attrs": {"name": "pic.png", "url": "https://x/pic.png"},
                }
            ],
        }
        assert adf_to_md(doc(node)) == "[pic.png](https://x/pic.png)"

    def test_media_without_url(self) -> None:
        node = {"type": "media", "attrs": {"id": "att-1"}}
        assert adf_to_md(doc(paragraph(text("x "), node))) == "x att-1"

    def test_inline_card(self) -> None:
        node = {
            "type": "inlineCard",
            "attrs": {"url": "https://x/doc", "title": "Doc"},
        }
        assert adf_to_md(doc(paragraph(node))) == "[Doc](https://x/doc)"

    def test_mention_and_emoji(self) -> None:
        mention = {"type": "mention", "attrs": {"text": "@Alice", "id": "a1"}}
        emoji = {"type": "emoji", "attrs": {"shortName": ":thumbsup:"}}
        assert adf_to_md(doc(paragraph(mention, text(" "), emoji))) == (
            "@Alice :thumbsup:"
        )


class TestMarks:
    def test_all_marks(self) -> None:
        cases = [
            ([{"type": "strong"}], "**x**"),
            ([{"type": "em"}], "*x*"),
            ([{"type": "code"}], "`x`"),
            ([{"type": "strike"}], "~~x~~"),
            ([{"type": "underline"}], "<u>x</u>"),
            ([{"type": "link", "attrs": {"href": "https://e"}}], "[x](https://e)"),
            ([{"type": "subsup", "attrs": {"type": "sub"}}], "<sub>x</sub>"),
            ([{"type": "subsup", "attrs": {"type": "sup"}}], "<sup>x</sup>"),
            ([{"type": "textColor", "attrs": {"color": "#ff0000"}}], "x"),
        ]
        for marks, expected in cases:
            assert adf_to_md(doc(paragraph(text("x", marks)))) == expected

    def test_nested_marks(self) -> None:
        marks = [{"type": "strong"}, {"type": "em"}]
        assert adf_to_md(doc(paragraph(text("x", marks)))) == "***x***"

    def test_link_without_href_is_plain(self) -> None:
        assert adf_to_md(doc(paragraph(text("x", [{"type": "link"}])))) == "x"


class TestUnknownSafety:
    def test_unknown_node_recurses_into_content(self, caplog) -> None:
        node = {
            "type": "futureBlock",
            "content": [paragraph(text("inner"))],
        }
        with caplog.at_level(logging.WARNING):
            result = adf_to_md(doc(node))
        assert result == "inner"
        assert any("futureBlock" in record.message for record in caplog.records)

    def test_unknown_node_warns_once(self, caplog) -> None:
        node = {"type": "novelNode", "content": [paragraph(text("x"))]}
        with caplog.at_level(logging.WARNING):
            adf_to_md(doc(node))
            adf_to_md(doc(node))
        warnings = [
            record
            for record in caplog.records
            if "novelNode" in record.message and "node" in record.message
        ]
        assert len(warnings) == 1

    def test_unknown_mark_emitted_as_text(self, caplog) -> None:
        with caplog.at_level(logging.WARNING):
            result = adf_to_md(doc(paragraph(text("x", [{"type": "glow"}]))))
        assert result == "x"

    def test_malformed_shapes_never_raise(self) -> None:
        assert adf_to_md({"type": "doc", "content": [None, 42, "odd"]}) == ""
        assert adf_to_md({"type": "heading", "attrs": {"level": "deep"}}) == ""
        assert adf_to_md({"type": "table", "content": [{"type": "tableRow"}]}) == ""
        assert adf_to_md(doc({"type": "paragraph", "attrs": None})) == ""
