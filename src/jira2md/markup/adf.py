"""Atlassian Document Format (ADF) to Markdown conversion.

Walks the ADF node/mark set used by Jira REST API v2 rich-text fields.
Unknown nodes recurse into ``content`` with a warn-once log line and
never raise, so future ADF additions degrade to their inner text.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

logger = logging.getLogger("jira2md")

_warned_types: set[str] = set()

_PANEL_LABELS = {
    "info": "Info",
    "note": "Note",
    "warning": "Warning",
    "success": "Success",
    "error": "Error",
}


def _children(node: Mapping[str, Any]) -> list[Any]:
    """Return the node's content list, tolerating missing/odd shapes."""
    content = node.get("content")
    return content if isinstance(content, list) else []


def _attrs(node: Mapping[str, Any]) -> dict[str, Any]:
    """Return the node attrs dict, tolerating missing/odd shapes."""
    attrs = node.get("attrs")
    return attrs if isinstance(attrs, dict) else {}


def _render_blocks(nodes: list[Any]) -> str:
    """Join rendered block-level children with blank lines."""
    parts = [rendered for rendered in map(_render_node, nodes) if rendered]
    return "\n\n".join(parts)


def _render_inline(nodes: list[Any]) -> str:
    """Concatenate rendered inline children without separators."""
    return "".join(_render_node(child) for child in nodes)


def _apply_marks(text: str, marks: Any) -> str:
    """Wrap text in each mark, innermost first."""
    if not isinstance(marks, list):
        return text
    for mark in marks:
        text = _apply_mark(text, mark)
    return text


def _apply_mark(text: str, mark: Any) -> str:
    """Apply a single ADF mark to already-rendered text."""
    if not isinstance(mark, Mapping):
        return text
    mark_type = str(mark.get("type") or "")
    attrs = _attrs(mark)
    if mark_type == "strong":
        return f"**{text}**"
    if mark_type == "em":
        return f"*{text}*"
    if mark_type == "code":
        return f"`{text}`"
    if mark_type == "strike":
        return f"~~{text}~~"
    if mark_type == "underline":
        return f"<u>{text}</u>"
    if mark_type == "link":
        href = str(attrs.get("href") or "")
        return f"[{text}]({href})" if href else text
    if mark_type == "subsup":
        tag = "sub" if str(attrs.get("type") or "").lower() == "sub" else "sup"
        return f"<{tag}>{text}</{tag}>"
    if mark_type == "textColor":
        return text  # colour carries no meaning in Markdown
    if mark_type and mark_type not in _warned_types:
        _warned_types.add(mark_type)
        logger.warning("Unrecognised ADF mark %s emitted as plain text", mark_type)
    return text


def _doc(node: Mapping[str, Any]) -> str:
    return _render_blocks(_children(node))


def _paragraph(node: Mapping[str, Any]) -> str:
    return _render_inline(_children(node))


def _text(node: Mapping[str, Any]) -> str:
    return _apply_marks(str(node.get("text") or ""), node.get("marks"))


def _heading(node: Mapping[str, Any]) -> str:
    try:
        level = int(_attrs(node).get("level") or 1)
    except (TypeError, ValueError):
        level = 1
    level = max(1, min(level, 6))
    inline = _render_inline(_children(node))
    return f"{'#' * level} {inline}" if inline else ""


def _list_items(node: Mapping[str, Any], marker: Callable[[int], str]) -> str:
    lines: list[str] = []
    index = 0
    for item in _children(node):
        if not isinstance(item, Mapping) or item.get("type") != "listItem":
            continue
        index += 1
        body = _render_list_item(item)
        first, *rest = body.split("\n")
        lines.append(f"{marker(index)} {first}")
        lines.extend(f"  {line}" if line else line for line in rest)
    return "\n".join(lines)


def _render_list_item(item: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for child in _children(item):
        if not isinstance(child, Mapping):
            continue
        if child.get("type") in ("bulletList", "orderedList"):
            parts.append(_render_node(child))
        else:
            parts.append(_render_inline(_children(child)))
    return "\n".join(part for part in parts if part)


def _bullet_list(node: Mapping[str, Any]) -> str:
    return _list_items(node, lambda _index: "-")


def _ordered_list(node: Mapping[str, Any]) -> str:
    return _list_items(node, lambda index: f"{index}.")


def _code_block(node: Mapping[str, Any]) -> str:
    language = str(_attrs(node).get("language") or "")
    text = _render_inline(_children(node))
    return f"```{language}\n{text}\n```"


def _blockquote(node: Mapping[str, Any]) -> str:
    body = _render_blocks(_children(node))
    return "\n".join(f"> {line}" if line else ">" for line in body.split("\n"))


def _rule(_node: Mapping[str, Any]) -> str:
    return "---"


def _hard_break(_node: Mapping[str, Any]) -> str:
    return "\n"


def _cell_text(node: Mapping[str, Any]) -> str:
    return _render_inline(_children(node)).replace("|", "\\|").replace("\n", " ")


def _table(node: Mapping[str, Any]) -> str:
    rows: list[str] = []
    separator_emitted = False
    for row in _children(node):
        if not isinstance(row, Mapping) or row.get("type") != "tableRow":
            continue
        cells = [
            _cell_text(cell)
            for cell in _children(row)
            if isinstance(cell, Mapping)
            and cell.get("type") in ("tableHeader", "tableCell")
        ]
        if not cells:
            continue
        rows.append("| " + " | ".join(cells) + " |")
        if not separator_emitted and any(
            isinstance(cell, Mapping) and cell.get("type") == "tableHeader"
            for cell in _children(row)
        ):
            rows.append("|" + "---|" * len(cells))
            separator_emitted = True
    return "\n".join(rows)


def _panel(node: Mapping[str, Any]) -> str:
    panel_type = str(_attrs(node).get("panelType") or "note")
    label = _PANEL_LABELS.get(panel_type, panel_type.title())
    body = _render_blocks(_children(node))
    quoted = "\n".join(f"> {line}" if line else ">" for line in body.split("\n"))
    return f"> **{label}**\n{quoted}"


def _media_single(node: Mapping[str, Any]) -> str:
    return _render_inline(_children(node))


def _media(node: Mapping[str, Any]) -> str:
    attrs = _attrs(node)
    name = str(attrs.get("name") or attrs.get("id") or "media")
    url = str(attrs.get("url") or "")
    if url:
        return f"[{name}]({url})"
    return name


def _inline_card(node: Mapping[str, Any]) -> str:
    attrs = _attrs(node)
    url = str(attrs.get("url") or "")
    title = str(attrs.get("title") or url)
    return f"[{title}]({url})" if url else title


def _mention(node: Mapping[str, Any]) -> str:
    attrs = _attrs(node)
    text = attrs.get("text")
    if text:
        return str(text)
    account = attrs.get("id") or attrs.get("accessLevel") or ""
    return f"@user_{account}"


def _emoji(node: Mapping[str, Any]) -> str:
    attrs = _attrs(node)
    short_name = str(attrs.get("shortName") or "")
    return short_name if short_name else str(attrs.get("text") or "")


def _expand(node: Mapping[str, Any]) -> str:
    title = str(_attrs(node).get("title") or "")
    body = _render_blocks(_children(node))
    if title:
        return f"**{title}**\n\n{body}" if body else f"**{title}**"
    return body


def _status(node: Mapping[str, Any]) -> str:
    text = str(_attrs(node).get("text") or "")
    return f"**{text}**" if text else ""


def _date(node: Mapping[str, Any]) -> str:
    return str(_attrs(node).get("timestamp") or "")


_NODE_HANDLERS: dict[str, Callable[[Mapping[str, Any]], str]] = {
    "doc": _doc,
    "paragraph": _paragraph,
    "text": _text,
    "heading": _heading,
    "bulletList": _bullet_list,
    "orderedList": _ordered_list,
    "listItem": _render_list_item,
    "codeBlock": _code_block,
    "blockquote": _blockquote,
    "rule": _rule,
    "hardBreak": _hard_break,
    "table": _table,
    "panel": _panel,
    "mediaSingle": _media_single,
    "media": _media,
    "inlineCard": _inline_card,
    "mention": _mention,
    "emoji": _emoji,
    "expand": _expand,
    "status": _status,
    "date": _date,
}


def _render_node(node: Any) -> str:
    """Render one ADF node; unknown types recurse into ``content``."""
    if not isinstance(node, Mapping):
        return ""
    node_type = str(node.get("type") or "")
    handler = _NODE_HANDLERS.get(node_type)
    if handler is None:
        if node_type and node_type not in _warned_types:
            _warned_types.add(node_type)
            logger.warning(
                "Unrecognised ADF node %s rendered from its content", node_type
            )
        return _render_blocks(_children(node)) or _render_inline(_children(node))
    try:
        return handler(node)
    except Exception as exc:  # noqa: BLE001 - ADF must never break rendering
        logger.warning("ADF node %s failed to render: %s", node_type, exc)
        return ""


def adf_to_md(node: Any) -> str:
    """Convert an ADF document node to Markdown.

    Args:
        node: Raw ADF payload (dict) from the REST API. Non-dict input
            renders as an empty string.

    Returns:
        Markdown text (block-level output, trailing newline stripped).
    """
    if not isinstance(node, Mapping):
        return ""
    if str(node.get("type") or "") == "doc":
        return _render_blocks(_children(node)).strip("\n")
    return _render_node(node)
