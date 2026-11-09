"""Render Anki card content from raw note fields and model definitions.

Extracted from apkg_reader.py. All rendering is pure: no I/O, no DB access.
"""

import html as _html
import re
from collections.abc import Callable

from bs4 import BeautifulSoup
from bs4.element import NavigableString, PageElement, Tag

QUESTION_FIELD_NAMES = {"front", "question", "prompt", "q"}
ANSWER_FIELD_NAMES = {"back", "answer", "implementation", "a", "response"}

_CLOZE_FIELD_RE = re.compile(r"\{\{cloze:([^}]+)\}\}")

# Matches {{FieldName}}, {{type:FieldName}}, {{hint:FieldName}}, {{#FieldName}}, {{/FieldName}}
_TEMPLATE_FIELD_RE = re.compile(r"\{\{(?:#|/|type:|hint:)?([^}:]+)\}\}")

ANKI_SPECIAL_FIELDS = frozenset(
    {"FrontSide", "Tags", "Type", "Deck", "Subdeck", "Card", "CardFlag"}
)
_ANKI_SPECIAL_FIELDS = ANKI_SPECIAL_FIELDS

# Turns a raw field value into display text (strip_html or _verbatim).
Cleaner = Callable[[str], str]


class ModelInfo:
    """Parsed Anki model (note type) metadata.

    plain_text marks spacedrep's own note types: their fields hold plain text
    and render verbatim. Other note types come from Anki, whose fields are HTML.
    """

    __slots__ = ("field_names", "templates", "model_type", "plain_text")

    def __init__(
        self,
        field_names: list[str],
        templates: list[dict[str, str]],
        model_type: int,
        *,
        plain_text: bool = False,
    ) -> None:
        self.field_names = field_names
        self.templates = templates
        self.model_type = model_type
        self.plain_text = plain_text


class NoteInfo:
    """Parsed Anki note row."""

    __slots__ = ("mid", "fields", "guid", "tags")

    def __init__(self, mid: str, fields: list[str], guid: str, tags: str) -> None:
        self.mid = mid
        self.fields = fields
        self.guid = guid
        self.tags = tags


def render_card(
    note_flds: str,
    model_info: ModelInfo,
    card_ord: int,
) -> tuple[str, str, dict[str, str]]:
    """Render a card's question, answer, and extra fields from raw note data.

    Args:
        note_flds: Raw field string from notes.flds (\\x1f-separated).
        model_info: Parsed model definition with field names, templates, type.
        card_ord: 0-based card ordinal.

    Returns:
        (question, answer, extra_fields): verbatim for plain-text models,
        with HTML stripped otherwise.
    """
    fields = note_flds.split("\x1f")
    field_names = model_info.field_names
    cleaner = _verbatim if model_info.plain_text else strip_html

    if model_info.model_type == 1:
        # Cloze model
        cloze_field_idx = _find_cloze_field(model_info, fields)
        raw_text = fields[cloze_field_idx] if cloze_field_idx < len(fields) else ""
        question_raw, answer_raw = render_cloze(raw_text, card_ord)
        question = cleaner(question_raw)
        answer = cleaner(answer_raw)
        extra: dict[str, str] = {}
        for i, fname in enumerate(field_names):
            if i != cloze_field_idx and i < len(fields):
                stripped = cleaner(fields[i])
                if stripped:
                    extra[fname] = stripped
        return (question, answer, extra)

    if len(model_info.templates) > 1:
        # Multi-template basic model (e.g., basic+reversed)
        return resolve_template_fields(
            model_info.templates, card_ord, fields, field_names, cleaner=cleaner
        )

    # Single-template basic model — use field name detection
    qi, ai = detect_field_mapping(field_names, None, None)
    return _build_qa_extra(fields, field_names, qi, ai, cleaner=cleaner)


def render_cloze(text: str, card_ord: int) -> tuple[str, str]:
    """Render cloze deletion text for a specific card ordinal.

    Args:
        text: Raw cloze text with {{c1::answer}} or {{c1::answer::hint}} syntax.
        card_ord: 0-based card ordinal (ord=0 -> c1, ord=1 -> c2).

    Returns:
        (question, answer) tuple with cloze markers resolved to plain text.
    """
    active_num = card_ord + 1
    pattern = r"\{\{c(\d+)::(.+?)(?:::(.+?))?\}\}"

    def q_replace(m: re.Match[str]) -> str:
        if int(m.group(1)) == active_num:
            return f"[{m.group(3)}]" if m.group(3) else "[...]"
        return m.group(2)

    def a_replace(m: re.Match[str]) -> str:
        return m.group(2)

    question = re.sub(pattern, q_replace, text, flags=re.DOTALL)
    answer = re.sub(pattern, a_replace, text, flags=re.DOTALL)
    return (question, answer)


def detect_field_mapping(
    field_names: list[str],
    question_field: str | None,
    answer_field: str | None,
) -> tuple[int, int]:
    """Returns (question_index, answer_index).

    Priority: explicit params > name matching > positional (0, 1).
    """
    names_lower = [n.lower() for n in field_names]

    # Question field
    if question_field:
        try:
            qi = names_lower.index(question_field.lower())
        except ValueError:
            msg = f"Question field '{question_field}' not found. Available: {field_names}"
            raise ValueError(msg) from None
    else:
        qi = find_field_index(names_lower, QUESTION_FIELD_NAMES)
        if qi is None:
            qi = 0

    # Answer field
    if answer_field:
        try:
            ai = names_lower.index(answer_field.lower())
        except ValueError:
            msg = f"Answer field '{answer_field}' not found. Available: {field_names}"
            raise ValueError(msg) from None
    else:
        ai = find_field_index(names_lower, ANSWER_FIELD_NAMES)
        if ai is None:
            ai = 1 if len(field_names) > 1 else 0

    return qi, ai


def find_field_index(names_lower: list[str], candidates: set[str]) -> int | None:
    """Find the first field name that matches a candidate set."""
    for i, name in enumerate(names_lower):
        if name in candidates:
            return i
    return None


def resolve_card_qa_fields(model_info: "ModelInfo", card_ord: int) -> tuple[int | None, int | None]:
    """Resolve the (question_field_idx, answer_field_idx) for a given card ord.

    For single-template basic models, uses name-based detection. For
    multi-template basic models (e.g. basic+reversed), parses the specific
    template at card_ord to find which field appears first in qfmt vs afmt.
    For cloze models, returns (None, None) — the "question" is the cloze
    text itself, not a separate field.
    """
    if model_info.model_type == 1:
        return (None, None)
    field_map = {name: i for i, name in enumerate(model_info.field_names)}
    if card_ord < len(model_info.templates):
        tmpl = model_info.templates[card_ord]
        qi = _first_real_field(tmpl.get("qfmt", ""), field_map)
        ai = _first_real_field(tmpl.get("afmt", ""), field_map)
        if qi is not None and ai is not None:
            return (qi, ai)
    return detect_field_mapping(model_info.field_names, None, None)


def strip_html(html: str) -> str:
    """Render Anki HTML as plain text, keeping its visible structure.

    Line breaks (<br>) and block ends (<p>, <div>, <li>, <tr>, <h1>-<h6>,
    <blockquote>) become newlines; list items get a "- " prefix indented two
    spaces per nesting level; inline <code>/<tt> become `text`; <pre> becomes
    a fenced block. Entities are unescaped. Runs of more than two newlines
    collapse to two, trailing spaces are stripped from each line, and the
    whole result is stripped.
    """
    if not html:
        return ""
    if "<" not in html:
        return _tidy(_html.unescape(html) if "&" in html else html)
    soup = BeautifulSoup(html, "html.parser")
    out = _TextBuilder()
    _render_children(soup, out, list_depth=0)
    return _tidy(out.getvalue())


_BLOCK_TAGS = frozenset(
    {"p", "div", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "hr", "table"}
)
_LIST_TAGS = frozenset({"ul", "ol"})
_INLINE_CODE_TAGS = frozenset({"code", "tt"})
_SKIP_TAGS = frozenset({"script", "style", "head", "title"})
_HTML_SPACE_RE = re.compile(r"[ \t\n\r\f\xa0]+")
_EXCESS_NEWLINES_RE = re.compile(r"\n{3,}")
_CODE_LANG_RE = re.compile(r"(?:^|\s)(?:language|lang)-([\w+#.-]+)")


class _TextBuilder:
    """Accumulates rendered text and tracks whether we sit at a line start."""

    __slots__ = ("_parts",)

    def __init__(self) -> None:
        self._parts: list[str] = []

    def _last_char(self) -> str:
        for part in reversed(self._parts):
            if part:
                return part[-1]
        return ""

    def at_line_start(self) -> bool:
        return self._last_char() in ("", "\n")

    def text(self, s: str) -> None:
        """Append HTML text: whitespace collapses to single spaces."""
        s = _HTML_SPACE_RE.sub(" ", s)
        if s.startswith(" ") and (self.at_line_start() or self._last_char() == " "):
            s = s[1:]
        if s:
            self._parts.append(s)

    def raw(self, s: str) -> None:
        """Append text verbatim (list prefixes, fenced code)."""
        if s:
            self._parts.append(s)

    def newline(self) -> None:
        """Hard line break; drops trailing spaces on the current line."""
        if self._parts:
            self._parts[-1] = self._parts[-1].rstrip(" \t")
        self._parts.append("\n")

    def ensure_newline(self) -> None:
        """Line break unless already at the start of a line."""
        if not self.at_line_start():
            self.newline()

    def getvalue(self) -> str:
        return "".join(self._parts)


def _render_children(node: Tag, out: _TextBuilder, *, list_depth: int) -> None:
    for child in node.children:
        _render_node(child, out, list_depth=list_depth)


def _render_node(node: PageElement, out: _TextBuilder, *, list_depth: int) -> None:
    if isinstance(node, NavigableString):
        # Comments, CDATA, doctypes and processing instructions are not text.
        if type(node) is NavigableString:
            out.text(str(node))
        return
    if not isinstance(node, Tag):
        return
    name = node.name.lower()
    if name in _SKIP_TAGS:
        return
    if name == "br":
        out.newline()
        # html.parser nests text inside <br> when <br> and <br/> are mixed.
        _render_children(node, out, list_depth=list_depth)
    elif name == "pre":
        _render_pre(node, out)
    elif name in _INLINE_CODE_TAGS:
        inner = _HTML_SPACE_RE.sub(" ", node.get_text()).strip()
        if inner:
            fence = "``" if "`" in inner else "`"
            pad = " " if fence == "``" else ""
            out.text(f"{fence}{pad}{inner}{pad}{fence}")
    elif name == "li":
        out.ensure_newline()
        out.raw("  " * max(list_depth - 1, 0) + "- ")
        _render_children(node, out, list_depth=list_depth)
        out.ensure_newline()
    elif name in _LIST_TAGS:
        out.ensure_newline()
        _render_children(node, out, list_depth=list_depth + 1)
        out.ensure_newline()
    elif name in ("td", "th"):
        prev = node.find_previous_sibling(["td", "th"])
        if prev is not None:
            out.text(" | ")
        _render_children(node, out, list_depth=list_depth)
    elif name in _BLOCK_TAGS:
        out.ensure_newline()
        _render_children(node, out, list_depth=list_depth)
        out.ensure_newline()
    else:
        _render_children(node, out, list_depth=list_depth)


def _render_pre(node: Tag, out: _TextBuilder) -> None:
    """Render <pre> as a fenced code block on its own lines."""
    for br in node.find_all("br"):
        br.insert_before("\n")
        br.unwrap()  # keep any text html.parser nested inside the <br>
    lang = ""
    for candidate in (node, node.find("code")):
        if isinstance(candidate, Tag):
            m = _CODE_LANG_RE.search(" ".join(candidate.get_attribute_list("class") or []))
            if m:
                lang = m.group(1)
                break
    body = node.get_text().replace("\xa0", " ").strip("\n").rstrip()
    out.ensure_newline()
    out.raw(f"```{lang}\n{body}\n```")
    out.newline()


def _tidy(text: str) -> str:
    """Strip trailing spaces per line, cap blank runs at one blank line, strip ends."""
    lines = [line.rstrip() for line in text.split("\n")]
    return _EXCESS_NEWLINES_RE.sub("\n\n", "\n".join(lines)).strip()


def _verbatim(text: str) -> str:
    """Return plain text as-is, trimming only surrounding whitespace."""
    return text.strip()


def resolve_template_fields(
    templates: list[dict[str, str]],
    card_ord: int,
    fields: list[str],
    field_names: list[str],
    question_field: str | None = None,
    answer_field: str | None = None,
    *,
    cleaner: Cleaner = strip_html,
) -> tuple[str, str, dict[str, str]]:
    """Resolve Q/A from a model template at a given ordinal.

    Args:
        templates: Model template list, each with 'qfmt' and 'afmt' keys.
        card_ord: 0-based template index.
        fields: Field values (split from note's flds).
        field_names: Field names from the model.
        question_field: Explicit question field override (ignored, uses template).
        answer_field: Explicit answer field override (ignored, uses template).
        cleaner: Turns each raw field into display text (default strips HTML).

    Returns:
        (question, answer, extra_fields) tuple, each passed through cleaner.
    """
    if card_ord >= len(templates):
        # Fallback: shouldn't happen, but be safe
        qi, ai = detect_field_mapping(field_names, question_field, answer_field)
        return _build_qa_extra(fields, field_names, qi, ai, cleaner=cleaner)

    tmpl = templates[card_ord]
    field_map = {name: i for i, name in enumerate(field_names)}

    q_idx = _first_real_field(tmpl.get("qfmt", ""), field_map)
    a_idx = _first_real_field(tmpl.get("afmt", ""), field_map)

    if q_idx is None or a_idx is None:
        qi, ai = detect_field_mapping(field_names, question_field, answer_field)
        return _build_qa_extra(fields, field_names, qi, ai, cleaner=cleaner)

    return _build_qa_extra(fields, field_names, q_idx, a_idx, cleaner=cleaner)


def find_cloze_field(minfo: ModelInfo, fields: list[str]) -> int:
    """Index of the field holding a cloze note's {{c1::...}} text."""
    return _find_cloze_field(minfo, fields)


def _find_cloze_field(minfo: ModelInfo, fields: list[str]) -> int:
    """Find the field index containing cloze content.

    Checks templates for {{cloze:FieldName}}, falls back to first field with
    cloze syntax.
    """
    # Check templates for {{cloze:FieldName}}
    field_map = {name: i for i, name in enumerate(minfo.field_names)}
    for tmpl in minfo.templates:
        m = _CLOZE_FIELD_RE.search(tmpl.get("qfmt", ""))
        if m:
            name = m.group(1).strip()
            if name in field_map:
                return field_map[name]

    # Fallback: first field that contains cloze markers
    cloze_marker = re.compile(r"\{\{c\d+::")
    for i, fval in enumerate(fields):
        if cloze_marker.search(fval):
            return i

    return 0  # last resort


def _first_real_field(template_text: str, field_map: dict[str, int]) -> int | None:
    """Find the first non-special field index referenced in a template string."""
    for m in _TEMPLATE_FIELD_RE.finditer(template_text):
        name = m.group(1).strip()
        if name not in _ANKI_SPECIAL_FIELDS and name in field_map:
            return field_map[name]
    return None


def _build_qa_extra(
    fields: list[str], field_names: list[str], qi: int, ai: int, *, cleaner: Cleaner = strip_html
) -> tuple[str, str, dict[str, str]]:
    """Build (question, answer, extra_fields) from field indices."""
    question = cleaner(fields[qi]) if qi < len(fields) else ""
    answer = cleaner(fields[ai]) if ai < len(fields) else ""
    extra: dict[str, str] = {}
    for i, fname in enumerate(field_names):
        if i != qi and i != ai and i < len(fields):
            stripped = cleaner(fields[i])
            if stripped:
                extra[fname] = stripped
    return (question, answer, extra)
