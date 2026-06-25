"""Unit tests for ``app.services.markdown``.

Covers the happy-path corpus (headings, code, tables, footnotes,
task-lists, links, images, deflists, blockquotes, formatting) plus a
hostile XSS corpus that asserts the sanitizer drops every dangerous
construct. ``# H1`` strip behavior and the ``data-language`` annotation
are pinned in dedicated tests.

The tests are intentionally string-assertion based: the contract for
B5/B11 is the HTML shape, not the AST, so we lock that shape here.
"""
from __future__ import annotations

import re

import pytest

from app.services.markdown import (
    ALLOWED_ATTRS,
    ALLOWED_TAGS,
    LINK_REL,
    URL_SCHEMES,
    render_markdown,
)


# ---------------------------------------------------------------------------
# Constants / helpers
# ---------------------------------------------------------------------------


def _contains(haystack: str, *needles: str) -> None:
    """Assert every needle appears in haystack (better failure messages)."""
    for needle in needles:
        assert needle in haystack, f"missing fragment: {needle!r}\n---\n{haystack}"


def _absent(haystack: str, *needles: str) -> None:
    for needle in needles:
        assert needle not in haystack, (
            f"unexpected fragment: {needle!r}\n---\n{haystack}"
        )


# Regex helpers for the security corpus. The contract is "no executable
# HTML survives", not "no dangerous substring appears" — markdown-it
# escapes raw HTML to text, so substrings can show up as visible
# (inert) characters which is acceptable.

# Matches a real <script> or <iframe>/<object>/<embed>/<form>/<style>/...
# opening tag — not an escaped one (those become "&lt;script").
_SCRIPT_TAG_RE = re.compile(r"<\s*script\b", re.IGNORECASE)
_DANGEROUS_OPEN_TAG_RE = re.compile(
    r"<\s*(iframe|object|embed|form|style|meta|base|svg|math|body|html|head|link|script|button|frame|frameset)\b",
    re.IGNORECASE,
)
# Matches an event-handler attribute (on*=) that survived as a real
# attribute, i.e. one that's preceded by whitespace inside a real tag.
# We approximate this by requiring " on...=" appearing inside an
# unescaped tag.
_EVENT_HANDLER_RE = re.compile(
    r"<[^<>]*\son[a-z]+\s*=", re.IGNORECASE
)
# Matches an unescaped <a> whose href starts with the javascript scheme.
_ANCHOR_HREF_JS_RE = re.compile(
    r'<a\b[^>]*\bhref\s*=\s*"javascript:', re.IGNORECASE
)
# Matches any unescaped tag with an href/src/srcset/formaction/style
# attribute whose value contains a dangerous scheme or CSS expression.
_DANGEROUS_ATTR_VALUE_RE = re.compile(
    r'<[^<>]*\b(?:href|src|srcset|action|formaction|background|style)\s*=\s*'
    r'"[^"]*(?:javascript:|vbscript:|expression\s*\()',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Module-level invariants
# ---------------------------------------------------------------------------


class TestModuleConstants:
    def test_url_schemes_locked(self) -> None:
        # Frozen contract — see §3.7 of phase2-architecture.md.
        assert URL_SCHEMES == frozenset({"http", "https", "mailto"})

    def test_link_rel_locked(self) -> None:
        # rel attributes that ride along on every surviving anchor.
        assert LINK_REL == "noopener noreferrer nofollow"

    def test_dangerous_tags_excluded(self) -> None:
        for tag in (
            "script",
            "iframe",
            "object",
            "embed",
            "style",
            "form",
            "button",
            "svg",
            "math",
        ):
            assert tag not in ALLOWED_TAGS

    def test_safe_tags_present(self) -> None:
        for tag in ("p", "pre", "code", "a", "img", "table", "input"):
            assert tag in ALLOWED_TAGS

    def test_input_attrs_constrained_to_task_lists(self) -> None:
        # task-list checkboxes are the only input the renderer emits;
        # the attribute set must not grow without review.
        assert ALLOWED_ATTRS["input"] == frozenset({"type", "checked", "disabled"})


# ---------------------------------------------------------------------------
# Empty / null inputs
# ---------------------------------------------------------------------------


class TestEmptyInputs:
    def test_empty_string_returns_empty(self) -> None:
        assert render_markdown("") == ""

    def test_whitespace_only_returns_no_content_tags(self) -> None:
        # markdown-it may emit an empty block; assert no script/dangerous
        # markup leaks out either way.
        out = render_markdown("   \n  \n  ")
        _absent(out, "<script", "javascript:", "<iframe")


# ---------------------------------------------------------------------------
# Leading H1 strip
# ---------------------------------------------------------------------------


class TestH1Strip:
    def test_strips_single_leading_h1(self) -> None:
        out = render_markdown("# Title To Drop\n\nBody paragraph.\n")
        _absent(out, "Title To Drop", "<h1")
        _contains(out, "<p>Body paragraph.</p>")

    def test_keeps_h1_after_first_line(self) -> None:
        out = render_markdown("Intro paragraph.\n\n# Real Heading\n")
        _contains(out, "<h1>Real Heading</h1>", "<p>Intro paragraph.</p>")

    def test_h2_at_top_is_preserved(self) -> None:
        out = render_markdown("## Subtitle\n\nbody")
        _contains(out, "<h2>Subtitle</h2>")

    def test_strips_only_one_leading_h1(self) -> None:
        out = render_markdown("# First\n# Second\n")
        # First is stripped (with the following blank); Second renders.
        _contains(out, "<h1>Second</h1>")
        # Ensure we did not accidentally double-strip and drop both.
        assert out.count("<h1>") == 1


# ---------------------------------------------------------------------------
# Inline / block prose
# ---------------------------------------------------------------------------


class TestProse:
    def test_emphasis_and_strong(self) -> None:
        out = render_markdown("This is *italic* and **bold** and ~~struck~~.")
        _contains(out, "<em>italic</em>", "<strong>bold</strong>")
        # markdown-it-py renders GFM strikethrough as <s>...</s>; some
        # versions emit <del>. Either tag is in the allowlist; what we
        # really care about is that the "struck" text content survived
        # the sanitizer.
        assert ">struck<" in out

    def test_inline_code(self) -> None:
        out = render_markdown("Use `os.replace` for atomic writes.")
        _contains(out, "<code>os.replace</code>")

    def test_blockquote(self) -> None:
        out = render_markdown("> quoted line")
        _contains(out, "<blockquote>", "quoted line", "</blockquote>")

    def test_unordered_list(self) -> None:
        out = render_markdown("- one\n- two\n- three\n")
        _contains(out, "<ul>", "<li>one</li>", "<li>two</li>", "<li>three</li>")

    def test_ordered_list(self) -> None:
        out = render_markdown("1. alpha\n2. beta\n")
        _contains(out, "<ol>", "<li>alpha</li>", "<li>beta</li>")

    def test_hr(self) -> None:
        out = render_markdown("para\n\n---\n\nmore")
        _contains(out, "<hr>")

    def test_headings_h2_through_h6(self) -> None:
        out = render_markdown("## two\n\n### three\n\n#### four\n\n##### five\n\n###### six")
        for h in ("h2", "h3", "h4", "h5", "h6"):
            _contains(out, f"<{h}>", f"</{h}>")


# ---------------------------------------------------------------------------
# Tables (GFM)
# ---------------------------------------------------------------------------


class TestTables:
    def test_basic_table_renders(self) -> None:
        src = (
            "| Col A | Col B |\n"
            "| --- | --- |\n"
            "| a1 | b1 |\n"
            "| a2 | b2 |\n"
        )
        out = render_markdown(src)
        _contains(
            out,
            "<table>",
            "<thead>",
            "<th>Col A</th>",
            "<th>Col B</th>",
            "<tbody>",
            "<td>a1</td>",
            "<td>b2</td>",
        )


# ---------------------------------------------------------------------------
# Fenced code (with data-language annotation)
# ---------------------------------------------------------------------------


class TestFencedCode:
    def test_python_fence_carries_language_metadata(self) -> None:
        out = render_markdown("```python\nprint('hi')\n```")
        _contains(
            out,
            'data-language="python"',
            'class="hljs language-python"',
        )
        # The opening <pre ...><code ...> sandwich is what highlight.js binds to.
        assert re.search(
            r'<pre data-language="python"><code class="hljs language-python" data-language="python">',
            out,
        )

    def test_fence_without_language_defaults_to_plaintext(self) -> None:
        out = render_markdown("```\njust text\n```")
        _contains(out, 'data-language="plaintext"', "language-plaintext")

    def test_fence_language_lowercased(self) -> None:
        out = render_markdown("```TypeScript\nconst x = 1;\n```")
        _contains(out, 'data-language="typescript"', "language-typescript")

    def test_fence_language_uses_first_token(self) -> None:
        # markdown-it ships extra info after the language; we keep only the
        # language token to match highlight.js' class convention.
        out = render_markdown("```rust no_run ignore\nfn main() {}\n```")
        _contains(out, 'data-language="rust"', "language-rust")
        _absent(out, "no_run", "language-rust no_run")

    def test_fence_escapes_html_in_source(self) -> None:
        out = render_markdown("```html\n<script>alert(1)</script>\n```")
        # The literal source must be HTML-escaped so the sanitizer sees
        # benign text, not real tags. Critically, no executable <script>
        # tag may appear at the document level.
        assert "<script>alert(1)</script>" not in out
        _contains(out, "&lt;script&gt;", "alert(1)")


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------


class TestLinks:
    def test_http_link_carries_safe_rel_and_target(self) -> None:
        out = render_markdown("[ok](https://example.com)")
        _contains(out, 'href="https://example.com"', 'target="_blank"')
        # rel must include the no-* triad to neutralize tabnabbing.
        for token in ("noopener", "noreferrer", "nofollow"):
            assert token in out

    def test_mailto_allowed(self) -> None:
        out = render_markdown("[mail](mailto:hi@example.com)")
        _contains(out, "mailto:hi@example.com")

    def test_javascript_scheme_does_not_produce_anchor(self) -> None:
        # markdown-it rejects unsafe schemes during parsing, so the
        # source falls through as inert text. Either way, no real
        # <a href="javascript:..."> may appear in the output.
        out = render_markdown("[click](javascript:alert(1))")
        assert not _ANCHOR_HREF_JS_RE.search(out)

    def test_data_html_scheme_does_not_produce_anchor(self) -> None:
        out = render_markdown(
            "[x](data:text/html,<script>alert(1)</script>)"
        )
        assert not re.search(r'<a [^>]*href="data:', out, re.IGNORECASE)
        # No real <script> element either.
        assert not _SCRIPT_TAG_RE.search(out)

    def test_vbscript_scheme_does_not_produce_anchor(self) -> None:
        out = render_markdown("[x](vbscript:msgbox(1))")
        assert not re.search(r'<a [^>]*href="vbscript:', out, re.IGNORECASE)

    def test_autolink_via_linkify(self) -> None:
        out = render_markdown("See https://example.com for more.")
        _contains(out, 'href="https://example.com"')


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------


class TestImages:
    def test_image_renders_with_alt(self) -> None:
        out = render_markdown("![alt text](https://cdn.example.com/a.png)")
        _contains(out, "<img", 'src="https://cdn.example.com/a.png"', 'alt="alt text"')

    def test_image_with_javascript_src_dropped(self) -> None:
        out = render_markdown("![x](javascript:alert(1))")
        # The src must not survive as a real <img> attribute.
        assert not re.search(r'<img\b[^>]*\bsrc\s*=\s*"javascript:', out, re.IGNORECASE)


# ---------------------------------------------------------------------------
# Plugins: footnotes, task lists, deflist
# ---------------------------------------------------------------------------


class TestPlugins:
    def test_footnote_renders(self) -> None:
        src = "Here is a fact[^1].\n\n[^1]: source"
        out = render_markdown(src)
        # Sanitizer must preserve the footnote reference link; the actual
        # element classes are mdit-py-plugins defaults and may evolve, so
        # we only assert the human-visible bits and the anchor stays.
        _contains(out, "<sup", "<a", "source")

    def test_task_list_renders_checkboxes(self) -> None:
        out = render_markdown("- [ ] todo\n- [x] done\n")
        _contains(out, '<input', 'type="checkbox"')
        # The "done" item must carry checked; the "todo" item must not.
        assert out.count("checked") >= 1
        # The disabled flag keeps users from toggling — task lists are
        # display-only in v1.
        assert "disabled" in out

    def test_deflist_renders(self) -> None:
        src = "term\n:   definition\n"
        out = render_markdown(src)
        # mdit-py-plugins emits <dl><dt><dd>; those tags are NOT in the
        # allowlist by design (rendering a dl/dt/dd was not in scope per
        # §3.7). The sanitizer should drop the wrappers but keep the text
        # content so authors don't lose information silently.
        _contains(out, "definition")


# ---------------------------------------------------------------------------
# Hostile XSS corpus
# ---------------------------------------------------------------------------


# Each entry is (label, markdown_source). Every output must satisfy the
# generic invariants in ``test_xss_corpus_is_neutralized``.
_XSS_CORPUS: list[tuple[str, str]] = [
    ("raw_script_tag", "<script>alert('xss')</script>"),
    (
        "raw_script_around_text",
        "before <script>window.location='http://evil'</script> after",
    ),
    ("img_onerror", '<img src=x onerror="alert(1)">'),
    ("img_onload", '<img src="https://ok/x.png" onload="alert(1)">'),
    ("a_onclick", '<a href="https://ok" onclick="alert(1)">x</a>'),
    ("link_javascript_scheme", "[x](javascript:alert(1))"),
    ("link_uppercase_javascript", "[x](JaVaScRiPt:alert(1))"),
    ("link_data_html", "[x](data:text/html,<script>alert(1)</script>)"),
    ("link_vbscript", "[x](vbscript:msgbox(1))"),
    ("iframe", '<iframe src="https://evil"></iframe>'),
    ("object", '<object data="https://evil/x.swf"></object>'),
    ("embed", '<embed src="https://evil/x.swf">'),
    ("svg_with_script", "<svg><script>alert(1)</script></svg>"),
    ("svg_onload", '<svg onload="alert(1)"></svg>'),
    ("math_action", '<math href="javascript:alert(1)">x</math>'),
    ("style_tag", "<style>body{background:url(javascript:alert(1))}</style>"),
    ("form_post", '<form action="https://evil"><input name=x></form>'),
    (
        "meta_refresh",
        '<meta http-equiv="refresh" content="0;url=https://evil">',
    ),
    ("base_tag", '<base href="https://evil/">'),
    ("body_onload", '<body onload="alert(1)">x</body>'),
    ("expression_css", '<div style="width:expression(alert(1))">x</div>'),
    ("html_in_code_fence", "```\n<script>alert(1)</script>\n```"),
    (
        "html_in_inline_code",
        "Use `<script>alert(1)</script>` carefully.",
    ),
    ("nested_a_with_js", '<a href="javascript:alert(1)"><b>click</b></a>'),
    ("img_srcset_js", '<img srcset="javascript:alert(1) 1x">'),
    ("img_with_formaction", '<button formaction="javascript:alert(1)">x</button>'),
]


_FORBIDDEN_FRAGMENTS: tuple[str, ...] = (
    # These substrings are forbidden in any form anywhere in the output.
    # They are the unambiguously executable / dangerous tokens that have
    # no legitimate reason to appear, even as visible escaped text in
    # our specific corpus inputs.
    "</script",
)


@pytest.mark.parametrize(
    ("label", "source"),
    _XSS_CORPUS,
    ids=[label for label, _ in _XSS_CORPUS],
)
def test_xss_corpus_is_neutralized(label: str, source: str) -> None:
    """Verify no executable HTML survives for any hostile input.

    The contract: nh3 + ``html=False`` together guarantee that the output
    contains no real dangerous tag, no event-handler attribute on a real
    tag, no real anchor/image with a javascript:/vbscript: scheme, and
    no closing ``</script>`` (which could break out of a containing
    context). Escaped text representations of dangerous tokens are
    acceptable because they render as inert characters to the user.
    """
    out = render_markdown(source)
    msg = f"[{label}] output:\n{out}"

    assert not _SCRIPT_TAG_RE.search(out), msg
    assert not _DANGEROUS_OPEN_TAG_RE.search(out), msg
    assert not _EVENT_HANDLER_RE.search(out), msg
    assert not _ANCHOR_HREF_JS_RE.search(out), msg
    assert not _DANGEROUS_ATTR_VALUE_RE.search(out), msg
    for needle in _FORBIDDEN_FRAGMENTS:
        assert needle.lower() not in out.lower(), (
            f"[{label}] forbidden fragment {needle!r} appeared in:\n{out}"
        )


# ---------------------------------------------------------------------------
# Inline HTML is escaped (defense in depth)
# ---------------------------------------------------------------------------


class TestInlineHtmlEscaping:
    def test_inline_html_is_escaped_not_rendered(self) -> None:
        out = render_markdown("Hello <b>world</b>")
        # html=False on MarkdownIt escapes the source; the visible text
        # ends up entity-encoded so the user can see what they typed.
        _absent(out, "<b>world</b>")
        # The escaped form lives inside the paragraph.
        _contains(out, "&lt;b&gt;")

    def test_html_comment_not_executed(self) -> None:
        # html=False escapes <!-- ... --> to visible text. That is safe
        # (no parser ever interprets the comment markers) — we only need
        # to assert no real comment node sneaks past the renderer.
        out = render_markdown("<!-- secret --> visible")
        assert "<!--" not in out
        _contains(out, "visible")


# ---------------------------------------------------------------------------
# Idempotence / determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_render_is_idempotent_across_calls(self) -> None:
        src = "# Skip me\n\nHello [link](https://example.com).\n\n```py\nx = 1\n```"
        first = render_markdown(src)
        second = render_markdown(src)
        assert first == second

    def test_no_h1_strip_when_no_leading_h1(self) -> None:
        src = "Just a paragraph.\n"
        assert "<p>Just a paragraph.</p>" in render_markdown(src)
