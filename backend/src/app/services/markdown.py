"""Markdown rendering and sanitization service.

Pure module that converts Markdown source to HTML safe to ship to the SPA
via ``v-html``. The pipeline mirrors §3.7 of
``docs/refactor/phase2-architecture.md``:

1. Strip a single leading ``# H1`` line (the card row owns the title).
2. Parse with markdown-it-py in GFM-like mode (``html=False``, linkify on,
   no typographer, no soft-break-as-hard-break).
3. Annotate fenced code blocks with ``data-language`` and a
   ``hljs language-<lang>`` class on the inner ``<code>`` so highlight.js
   can pick them up without re-parsing.
4. Render to HTML.
5. Sanitize via nh3 against an explicit tag/attribute allowlist (defense
   in depth — ``html=False`` already escapes inline HTML in the source).

The function is pure: no I/O, no DB. Caching is handled by the cards
service which persists the result to ``cards.body_html`` on every
mutation.
"""
from __future__ import annotations

import re
from typing import Any, Final

import nh3
from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.deflist import deflist_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.tasklists import tasklists_plugin

__all__ = [
    "ALLOWED_ATTRS",
    "ALLOWED_TAGS",
    "LINK_REL",
    "URL_SCHEMES",
    "render_markdown",
]


# Strip a single leading "# Heading" line and any blank lines that follow.
# Anchored at start of string (default re flags); count=1 in re.sub keeps
# this surgical so an internal "# Title" line is rendered as a real H1.
_H1_STRIP_RE: Final[re.Pattern[str]] = re.compile(r"^# .*\n+")


ALLOWED_TAGS: Final[frozenset[str]] = frozenset(
    {
        "p",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "ul",
        "ol",
        "li",
        "blockquote",
        "pre",
        "code",
        "a",
        "img",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "hr",
        "em",
        "strong",
        "del",
        "s",
        "br",
        "span",
        "sup",
        "sub",
        "div",
        "input",
    }
)
"""HTML tags retained by the sanitizer. Frozen — adding a tag is a
security-review item, not a routine refactor."""


ALLOWED_ATTRS: Final[dict[str, frozenset[str]]] = {
    # Note: ``rel`` is intentionally absent. nh3 manages the ``rel`` value
    # itself when ``link_rel`` is set (passing it here is a ValueError).
    "a": frozenset({"href", "title", "target"}),
    "img": frozenset({"src", "alt", "title", "loading"}),
    "code": frozenset({"class", "data-language"}),
    "pre": frozenset({"class", "data-language"}),
    "span": frozenset({"class"}),
    "div": frozenset({"class"}),
    "th": frozenset({"align", "scope"}),
    "td": frozenset({"align"}),
    "input": frozenset({"type", "checked", "disabled"}),
}
"""Per-tag attribute allowlist. ``class`` is intentionally narrow — only
on the inline-code/code-card stack and on ``span``/``div`` for prose
helpers."""


URL_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https", "mailto"})
"""Schemes accepted in ``href``/``src`` attributes. Notably absent:
``javascript:``, ``data:``, ``vbscript:``, ``file:``."""


LINK_REL: Final[str] = "noopener noreferrer nofollow"
"""Forced ``rel`` value on every surviving ``<a>``. Combined with
``target="_blank"`` (set via nh3's ``set_tag_attribute_values``) this
neutralizes reverse-tabnabbing and search-engine link-equity transfer."""


def _render_fence(
    tokens: list[Token],
    idx: int,
    options: Any,  # markdown-it renderer signature; unused here
    env: Any,  # ditto
) -> str:
    """Render a fenced code block with language metadata.

    Output shape (broken across lines for readability — actual output is
    a single line)::

        <pre data-language="LANG"
          ><code class="hljs language-LANG" data-language="LANG"
            >escaped source</code
        ></pre>

    ``LANG`` is the lowercased first whitespace-separated token of the
    fence info string, defaulting to ``plaintext`` when no info is
    present. The ``hljs`` class is the surface highlight.js'
    ``highlightElement`` looks for; pre-stamping it removes a re-parse
    pass in the SPA's ``useEnhanceCodeBlocks`` composable.
    """
    del options, env  # explicitly unused
    token = tokens[idx]
    info = (token.info or "").strip()
    first_word = info.split(maxsplit=1)[0] if info else ""
    lang = (first_word or "plaintext").lower()
    # markdown-it ships utils.escapeHtml; we inline the same five
    # substitutions to keep the function side-effect-free and avoid
    # depending on the renderer object's internals.
    content = (
        token.content.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    return (
        f'<pre data-language="{lang}">'
        f'<code class="hljs language-{lang}" data-language="{lang}">'
        f"{content}</code></pre>\n"
    )


def _build_md() -> MarkdownIt:
    md = MarkdownIt(
        "gfm-like",
        {
            "linkify": True,
            "html": False,
            "breaks": False,
            "typographer": False,
        },
    )
    md = md.use(footnote_plugin).use(deflist_plugin).use(tasklists_plugin)
    md.renderer.rules["fence"] = _render_fence
    return md


# Build the parser once at import time. ``MarkdownIt`` is safe to share
# across calls when the configuration is not mutated, which we guarantee
# by treating ``_MD`` as final.
_MD: Final[MarkdownIt] = _build_md()


def _strip_h1(md: str) -> str:
    return _H1_STRIP_RE.sub("", md, count=1)


def render_markdown(md: str) -> str:
    """Render Markdown source to sanitized HTML.

    :param md: Raw Markdown source. Empty / falsy input returns ``""``.
    :returns: Sanitized HTML. Inline HTML in the source is escaped before
        sanitization (``html=False``) and then sanitized again by nh3 so
        a regression in either layer still leaves output inside the
        allowlist.
    """
    if not md:
        return ""
    stripped = _strip_h1(md)
    html = _MD.render(stripped)
    return nh3.clean(
        html,
        tags=set(ALLOWED_TAGS),
        attributes={tag: set(attrs) for tag, attrs in ALLOWED_ATTRS.items()},
        url_schemes=set(URL_SCHEMES),
        link_rel=LINK_REL,
        # Force every surviving anchor to open in a new tab. nh3 already
        # filtered the tag/attr through the allowlist; this only sets the
        # value, so it cannot resurrect a dropped anchor.
        set_tag_attribute_values={"a": {"target": "_blank"}},
    )
