"""Jira wiki markup to Markdown conversion.

Pure function ``wiki_to_md`` with no I/O. Code and ``{noformat}``
blocks are extracted to opaque placeholders before any substitution
and restored last, so inline formatting inside them is never
transformed.

Two modes:

- ``extended=True`` (default) applies the full rule table:
  strikethrough, ``<u>`` underline, colour stripping, ``{anchor}`` /
  ``{toc}`` drops, mention resolution via ``users``, image asset
  rewriting, plain-text escaping, and warn-once unknown macros.
- ``extended=False`` is the conservative mode: underline and colour
  become HTML tags, strikethrough and plain text pass through
  unescaped, ``{anchor}`` survives, and images keep their original
  target instead of being rewritten into the assets directory.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping

logger = logging.getLogger("jira2md")

_warned_macros: set[str] = set()

_URL_PATTERN = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)


def reset_macro_warnings() -> None:
    """Clear the warn-once state (used by tests)."""
    _warned_macros.clear()


def _extract_blocks(
    text: str,
    pattern: str,
    transform_fn: Callable[[re.Match[str]], str],
    storage: list[str],
    prefix: str,
    flags: int = 0,
) -> str:
    """Replace pattern matches with placeholders, storing transforms.

    Args:
        text: Input text to process.
        pattern: Regex pattern to match blocks.
        transform_fn: Function transforming the match to target format.
        storage: List storing the transformed blocks.
        prefix: Placeholder prefix (e.g. "CODEBLOCK").
        flags: Regex flags to pass to ``re.sub``.

    Returns:
        Text with matches replaced by placeholders.
    """

    def _replacer(match: re.Match[str]) -> str:
        transformed = transform_fn(match)
        placeholder = f"\x00{prefix}{len(storage)}\x00"
        storage.append(transformed)
        return placeholder

    return re.sub(pattern, _replacer, text, flags=flags)


def _restore_blocks(text: str, storage: list[str], prefix: str) -> str:
    """Restore placeholders in reverse order to avoid index collisions.

    Args:
        text: Text containing placeholders.
        storage: Blocks stored during extraction.
        prefix: Placeholder prefix used during extraction.

    Returns:
        Text with placeholders replaced by the stored blocks.
    """
    for index in range(len(storage) - 1, -1, -1):
        text = text.replace(f"\x00{prefix}{index}\x00", storage[index])
    return text


def _convert_list(match: re.Match[str]) -> str:
    """Convert a Jira list marker line to Markdown."""
    jira_bullets = match.group(1)
    content = match.group(2)
    indent = " " * ((len(jira_bullets) - 1) * 2)
    prefix = "1." if jira_bullets[-1] == "#" else "-"
    return f"{indent}{prefix} {content}"


def _convert_panel(params: str | None, content: str, *, extended: bool) -> str:
    """Convert a Jira {panel} block to Markdown."""
    title = ""
    if params:
        title_match = re.search(r"title=([^|}]+)", params)
        if title_match:
            title = title_match.group(1).strip()
    content = content.strip()
    if extended:
        quoted = "\n".join(f"> {line}" for line in content.split("\n"))
        if title:
            return f"\n> **{title}**\n{quoted}\n"
        return f"\n{quoted}\n"
    if title:
        return f"\n**{title}**\n{content}\n"
    return f"\n{content}\n"


def _resolve_mentions(
    text: str, users: Mapping[str, str] | None, storage: list[str]
) -> str:
    """Resolve ``[~accountid:...]`` mentions to protected placeholders."""

    def _replace(match: re.Match[str]) -> str:
        account_id = match.group(1)
        if users and account_id in users:
            resolved = f"@{users[account_id]}"
        else:
            resolved = f"@user_{account_id}"
        placeholder = f"\x00MENTION{len(storage)}\x00"
        storage.append(resolved)
        return placeholder

    return re.sub(r"\[~accountid:([^\]]+)\]", _replace, text)


def _image_target(
    name: str,
    *,
    extended: bool,
    assets_dir: str,
    asset_urls: Mapping[str, str] | None = None,
) -> str:
    """Rewrite bare image filenames into the assets directory."""
    if not extended:
        return name
    if asset_urls and name in asset_urls:
        return asset_urls[name]
    if _URL_PATTERN.match(name) or name.startswith("/"):
        return name
    return f"{assets_dir}/{name}"


def _convert_tables(output: str) -> str:
    """Convert Jira table headers (||) to GFM pipe tables."""
    lines = output.split("\n")
    index = 0
    while index < len(lines):
        if "||" in lines[index]:
            lines[index] = lines[index].replace("||", "|")
            header_cells = lines[index].count("|") - 1
            if header_cells > 0:
                separator_line = "|" + "---|" * header_cells
                lines.insert(index + 1, separator_line)
                index += 1
        index += 1
    return "\n".join(lines)


def _warn_unknown_macros(output: str) -> None:
    """Log each unrecognised ``{macro}`` once per macro name."""
    for match in re.finditer(r"\{([a-zA-Z][a-zA-Z0-9_-]*)(?::[^}]*)?\}", output):
        name = match.group(1).lower()
        if name not in _warned_macros:
            _warned_macros.add(name)
            logger.warning("Unrecognised wiki macro {%s} emitted as-is", name)


def _escape_plain_text(output: str) -> str:
    """Escape leftover formatting characters outside generated links."""
    protected: list[str] = []
    output = _extract_blocks(
        output,
        r"!?\[[^\]]*\]\([^)]*\)",
        lambda match: match.group(0),
        protected,
        "MDLINK",
    )
    output = re.sub(r"(?<!\*)\*(?!\*)", r"\\*", output)
    output = re.sub(r"(?<!_)_(?!_)", r"\\_", output)
    output = output.replace("[", r"\[").replace("]", r"\]")
    return _restore_blocks(output, protected, "MDLINK")


def wiki_to_md(
    text: str,
    *,
    base_url: str | None = None,
    users: Mapping[str, str] | None = None,
    extended: bool = True,
    assets_dir: str = "assets",
    asset_urls: Mapping[str, str] | None = None,
) -> str:
    """Convert Jira wiki markup to Markdown.

    Args:
        text: Wiki markup source text.
        base_url: Jira base URL for resolving relative link targets.
        users: Account id to display name map for mention resolution.
        extended: Full conversion rule table; ``False`` selects the
            conservative mode (HTML tags for underline and colour, no
            plain-text escaping, no image asset rewriting).
        assets_dir: Prefix for rewritten inline image references.
        asset_urls: Bare filename to target map for ``!name!`` image
            references (downloaded asset paths or content URLs).

    Returns:
        Markdown text.
    """
    if not text:
        return ""

    output = text
    code_blocks: list[str] = []
    inline_codes: list[str] = []

    def _jira_code_to_md(match: re.Match[str]) -> str:
        lang = match.group(1) or ""
        return f"```{lang}\n{match.group(2)}\n```"

    output = _extract_blocks(
        output,
        r"\{code(?::([a-z]+))?\}([\s\S]*?)\{code\}",
        _jira_code_to_md,
        code_blocks,
        "CODEBLOCK",
        flags=re.MULTILINE,
    )
    output = _extract_blocks(
        output,
        r"\{noformat\}([\s\S]*?)\{noformat\}",
        lambda match: f"```\n{match.group(1)}\n```",
        code_blocks,
        "CODEBLOCK",
    )
    output = _extract_blocks(
        output,
        r"\{\{([^}]+)\}\}",
        lambda match: f"`{match.group(1)}`",
        inline_codes,
        "INLINECODE",
    )

    mention_store: list[str] = []
    if extended:
        output = re.sub(r"\{anchor:[^}]*\}", "", output)
        output = re.sub(r"\{toc(?::[^}]*)?\}", "", output)
        output = _resolve_mentions(output, users, mention_store)
        output = re.sub(r"(?<!\\)<", r"\\<", output)
        output = output.replace("`", r"\`")

    # Block quotes
    if extended:
        output = re.sub(
            r"^bq\.(.*)$",
            lambda match: f"> {match.group(1).lstrip()}\n",
            output,
            flags=re.MULTILINE,
        )
    else:
        output = re.sub(r"^bq\.(.*?)$", r"> \1\n", output, flags=re.MULTILINE)

    # Text formatting (bold, italic) and lists
    formatting_store: list[str] = []
    if extended:
        # Lists first, so ***/## markers survive the emphasis pass.
        output = re.sub(
            r"^((?:#|-|\+|\*)+) (.*)$",
            _convert_list,
            output,
            flags=re.MULTILINE,
        )

        # Boundary-aware matching: emphasis markers must sit at word
        # boundaries, so snake_case and "2 * 3" stay plain text and
        # the escaping pass below can protect them.
        def _fmt_boundary(match: re.Match[str]) -> str:
            marker = "**" if match.group(2) == "*" else "*"
            converted = f"{marker}{match.group(3)}{marker}"
            placeholder = f"\x00FMT{len(formatting_store)}\x00"
            formatting_store.append(converted)
            return f"{match.group(1)}{placeholder}"

        output = re.sub(
            r"(^|[\s(])([*_])(\S(?:[^\n]*?\S)?)\2(?=[\s).,;:!?]|$)",
            _fmt_boundary,
            output,
            flags=re.MULTILINE,
        )
    else:
        output = re.sub(
            r"([*_])(.*?)\1",
            lambda match: (
                ("**" if match.group(1) == "*" else "*")
                + match.group(2)
                + ("**" if match.group(1) == "*" else "*")
            ),
            output,
        )
        output = re.sub(
            r"^((?:#|-|\+|\*)+) (.*)$",
            _convert_list,
            output,
            flags=re.MULTILINE,
        )

    # Headers
    output = re.sub(
        r"^h([0-6])\.(.*)$",
        lambda match: "#" * int(match.group(1)) + match.group(2),
        output,
        flags=re.MULTILINE,
    )

    # Citation (non-overlapping alternation avoids catastrophic backtracking)
    output = re.sub(r"\?\?([^?]+(?:\?[^?]+)*)\?\?", r"<cite>\1</cite>", output)

    # Underlined text
    if extended:
        output = re.sub(r"\+([^+]*)\+", r"<u>\1</u>", output)
    else:
        output = re.sub(r"\+([^+]*)\+", r"<ins>\1</ins>", output)

    # Superscript / subscript
    output = re.sub(r"\^([^^]*)\^", r"<sup>\1</sup>", output)
    output = re.sub(r"~([^~]*)~", r"<sub>\1</sub>", output)

    # Strikethrough; conservative mode leaves ``-text-`` untouched
    if extended:
        output = re.sub(
            r"(^|(?<=\s))-([^\s-][^-]*?)-(?=\s|$)",
            r"\1~~\2~~",
            output,
            flags=re.MULTILINE,
        )

    # Quote blocks
    output = re.sub(
        r"\{quote\}([\s\S]*)\{quote\}",
        lambda match: "\n".join(f"> {line}" for line in match.group(1).split("\n")),
        output,
        flags=re.MULTILINE,
    )

    # Panel blocks
    output = re.sub(
        r"\{panel(?::([^}]*))?\}([\s\S]*?)\{panel\}",
        lambda match: _convert_panel(match.group(1), match.group(2), extended=extended),
        output,
        flags=re.MULTILINE,
    )

    # Images: alt text, other parameters, bare reference
    def _img(match: re.Match[str]) -> str:
        return _image_target(
            match.group(1),
            extended=extended,
            assets_dir=assets_dir,
            asset_urls=asset_urls,
        )

    output = re.sub(
        r"!([^|\n\s]+)\|([^\n!]*)alt=([^\n!\,]+?)(,([^\n!]*))?!",
        lambda match: f"![{match.group(3)}]({_img(match)})",
        output,
    )
    output = re.sub(
        r"!([^|\n\s]+)\|([^\n!]*)!",
        lambda match: f"![]({_img(match)})",
        output,
    )
    output = re.sub(
        r"!([^\n\s!]+)!",
        lambda match: f"![]({_img(match)})",
        output,
    )

    # Links
    if extended and base_url:

        def _link_target(url: str) -> str:
            if url.startswith("/"):
                return f"{base_url.rstrip('/')}{url}"
            return url

        output = re.sub(
            r"\[([^|]+)\|(.+?)\]",
            lambda match: f"[{match.group(1)}]({_link_target(match.group(2))})",
            output,
        )
    else:
        output = re.sub(r"\[([^|]+)\|(.+?)\]", r"[\1](\2)", output)
    output = re.sub(r"\[(.+?)\]([^\(])", r"\1\2", output)

    # Coloured text
    if extended:
        output = re.sub(
            r"\{color:([^}]+)\}([\s\S]*?)\{color\}",
            r"\2",
            output,
            flags=re.MULTILINE,
        )
    else:
        output = re.sub(
            r"\{color:([^}]+)\}([\s\S]*?)\{color\}",
            r"<span style=\"color:\1\">\2</span>",
            output,
            flags=re.MULTILINE,
        )

    # GFM tables
    output = _convert_tables(output)

    if extended:
        # Horizontal rules and hard line breaks
        output = re.sub(r"^-{4,}$", "---", output, flags=re.MULTILINE)
        output = re.sub(r"\\\\[ \t]*$", "  ", output, flags=re.MULTILINE)
        _warn_unknown_macros(output)
        output = _escape_plain_text(output)

    # Restore protected spans, then code and inline code last
    output = _restore_blocks(output, mention_store, "MENTION")
    output = _restore_blocks(output, formatting_store, "FMT")
    output = _restore_blocks(output, code_blocks, "CODEBLOCK")
    output = _restore_blocks(output, inline_codes, "INLINECODE")

    return output
