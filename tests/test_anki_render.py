"""Tests for pure card rendering (no DB)."""

from spacedrep.anki_render import ModelInfo, render_card

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
    assert answer == "bold x"


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
