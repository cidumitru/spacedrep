"""Tests for pure card rendering (no DB)."""

from spacedrep.anki_render import ModelInfo, render_card, strip_html

# Field names and templates mirror spacedrep's own note types (anki_schema).
_BASIC_FIELDS = ["Question", "Answer"]
_BASIC_TEMPLATES = [{"qfmt": "{{Question}}", "afmt": '{{FrontSide}}<hr id="answer">{{Answer}}'}]
_REVERSED_TEMPLATES = [
    *_BASIC_TEMPLATES,
    {"qfmt": "{{Answer}}", "afmt": '{{FrontSide}}<hr id="answer">{{Question}}'},
]
_CLOZE_FIELDS = ["Text", "Back Extra"]
_CLOZE_TEMPLATES = [{"qfmt": "{{cloze:Text}}", "afmt": "{{cloze:Text}}<br>{{Back Extra}}"}]


def test_plain_text_basic_is_verbatim() -> None:
    """Generics and fenced code survive untouched; only outer whitespace is trimmed."""
    model = ModelInfo(_BASIC_FIELDS, _BASIC_TEMPLATES, 0, plain_text=True)
    code = "```csharp\nvar xs = new List<int>();\nif (a < b && c > d) {}\n```"
    question, answer, extra = render_card(f"  Func<int> f = () => 1;\n\x1f{code}", model, 0)
    assert question == "Func<int> f = () => 1;"
    assert answer == code
    assert extra == {}


def test_plain_text_extra_fields_verbatim() -> None:
    model = ModelInfo([*_BASIC_FIELDS, "Notes"], _BASIC_TEMPLATES, 0, plain_text=True)
    _, _, extra = render_card("Q\x1fA\x1fSpan<byte>", model, 0)
    assert extra == {"Notes": "Span<byte>"}


def test_html_model_strips_tags() -> None:
    """Models not flagged plain_text (the default, e.g. Anki imports) keep stripping HTML."""
    model = ModelInfo(["Front", "Back"], [{"qfmt": "{{Front}}", "afmt": "{{Back}}"}], 0)
    question, answer, _ = render_card("<b>x</b>\x1f<b>bold</b> <br>x", model, 0)
    assert question == "x"
    assert answer == "bold\nx"


def test_plain_text_cloze_keeps_angle_brackets() -> None:
    model = ModelInfo(_CLOZE_FIELDS, _CLOZE_TEMPLATES, 1, plain_text=True)
    question, answer, extra = render_card(
        "{{c1::List<int>}} is generic\x1fsee IEnumerable<T>", model, 0
    )
    assert question == "[...] is generic"
    assert answer == "List<int> is generic"
    assert extra == {"Back Extra": "see IEnumerable<T>"}


def test_plain_text_reversed_both_ordinals_verbatim() -> None:
    model = ModelInfo(_BASIC_FIELDS, _REVERSED_TEMPLATES, 0, plain_text=True)
    flds = "List<int>\x1fIEnumerable<T>"
    assert render_card(flds, model, 0)[:2] == ("List<int>", "IEnumerable<T>")
    assert render_card(flds, model, 1)[:2] == ("IEnumerable<T>", "List<int>")


def test_plain_text_does_not_unescape_entities() -> None:
    """Verbatim means verbatim: HTML entities are not decoded."""
    model = ModelInfo(_BASIC_FIELDS, _BASIC_TEMPLATES, 0, plain_text=True)
    question, answer, _ = render_card("&lt;int&gt;\x1fVec<T> is Vec&lt;T&gt; in HTML", model, 0)
    assert question == "&lt;int&gt;"
    assert answer == "Vec<T> is Vec&lt;T&gt; in HTML"


# ---------------------------------------------------------------------------
# strip_html: structure-preserving rendering of Anki HTML
# ---------------------------------------------------------------------------


def test_strip_html_unordered_list() -> None:
    assert strip_html("<ul><li>one</li><li>two</li><li>three</li></ul>") == (
        "- one\n- two\n- three"
    )


def test_strip_html_br_separated_lines() -> None:
    assert strip_html("first<br>second<br/>third") == "first\nsecond\nthird"


def test_strip_html_inline_code() -> None:
    assert strip_html("Call <code>len(xs)</code> or <tt>xs.size()</tt>.") == (
        "Call `len(xs)` or `xs.size()`."
    )


def test_strip_html_pre_block() -> None:
    html = "Example:<pre>def f(x):\n    return x &lt; 1\n</pre>Done"
    assert strip_html(html) == "Example:\n```\ndef f(x):\n    return x < 1\n```\nDone"


def test_strip_html_pre_with_br() -> None:
    assert strip_html("<pre>a<br>b<br/>c</pre>") == "```\na\nb\nc\n```"


def test_strip_html_pre_code_language() -> None:
    html = '<pre><code class="language-python">print(1)</code></pre>'
    assert strip_html(html) == "```python\nprint(1)\n```"


def test_strip_html_nested_lists() -> None:
    html = "<ul><li>a<ul><li>b<ol><li>c</li></ol></li></ul></li><li>d</li></ul>"
    assert strip_html(html) == "- a\n  - b\n    - c\n- d"


def test_strip_html_entities_unescaped() -> None:
    assert strip_html("&lt;int&gt;") == "<int>"
    assert strip_html("<div>List&lt;int&gt; &amp; Map&lt;K,V&gt;</div>") == ("List<int> & Map<K,V>")


def test_strip_html_block_ends_become_newlines() -> None:
    html = "<h1>Title</h1><p>Para</p><div>Div</div><blockquote>Quote</blockquote>tail"
    assert strip_html(html) == "Title\nPara\nDiv\nQuote\ntail"


def test_strip_html_table_rows() -> None:
    html = "<table><tr><td>a</td><td>b</td></tr><tr><td>c</td><td>d</td></tr></table>"
    assert strip_html(html) == "a | b\nc | d"


def test_strip_html_collapses_blank_runs_and_trailing_spaces() -> None:
    assert strip_html("a   <br><br><br><br>  b  ") == "a\n\nb"
    assert strip_html("<div>a</div><div><br></div><div>b</div>") == "a\n\nb"


def test_strip_html_inline_whitespace_and_nbsp() -> None:
    assert strip_html("<b>bold</b>\n  text&nbsp;here") == "bold text here"


def test_strip_html_ignores_comments_and_style() -> None:
    assert strip_html("<style>.x{color:red}</style>a<!-- hidden -->b") == "ab"


def test_html_model_renders_structure() -> None:
    model = ModelInfo(["Front", "Back"], [{"qfmt": "{{Front}}", "afmt": "{{Back}}"}], 0)
    _, answer, _ = render_card("Q\x1f<ul><li>x</li><li><code>y</code></li></ul>", model, 0)
    assert answer == "- x\n- `y`"


def test_plain_text_model_not_restructured() -> None:
    model = ModelInfo(_BASIC_FIELDS, _BASIC_TEMPLATES, 0, plain_text=True)
    _, answer, _ = render_card("Q\x1f<ul><li>x</li></ul>", model, 0)
    assert answer == "<ul><li>x</li></ul>"
