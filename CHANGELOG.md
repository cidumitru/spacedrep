# Changelog

## 0.5.2 — 2026-11-09

All existing commands, JSON output shapes, exit codes and error codes are unchanged.

### Added

- **Extra fields on the write path.** `card add`, `card add-reversed` and
  `card update` take a repeatable `--field NAME=VALUE` (split on the first `=`).
  `card add-bulk` items take `"extra_fields": {"NAME": "VALUE"}` for the `basic` and
  `reversed` types. Cloze items with non-empty `extra_fields` are rejected with
  `bulk_input_error`. The MCP tools `add_card`, `add_reversed_card` and `update_card`
  take `extra_fields_json`, a JSON object passed as a string because MCP tool
  parameters must be primitive types. `add_cards_bulk` items accept `extra_fields`.
  Extras come back under `extra_fields` in `card get` / `card next`.
  - On spacedrep's own basic and reversed note types, an unknown NAME is appended
    to the note type's fields and shown on the answer side in Anki through
    `{{#NAME}}<div class="NAME">{{NAME}}</div>{{/NAME}}`. Existing fields are never
    reordered or renamed, and Question/Answer stay at ord 0 and 1.
  - On imported Anki note types, NAME must match one of the note type's fields
    exactly (case-sensitive). An unknown NAME fails with `invalid_field`, and the
    error lists the note type's fields.
  - `card update --field NAME=` clears a field. A field that renders as the card's
    question or answer is refused, and the error points at `--question` /
    `--answer`. For a cloze note, the cloze text field points at `card update-cloze`.
  - Re-adding a card (same question and deck) keeps extras already on the note
    unless it sets them again. `card update-cloze` keeps the note's other fields,
    such as Back Extra.
  - A new field name cannot be empty, contain whitespace, `\x1f`, `{`, `}`, `:`
    or `"`, start with `#`, `/` or `^`, be one of Anki's reserved template names
    (`FrontSide`, `Tags`, ...), or differ only in case from an existing field.
- `deck import` accepts `.colpkg` files as well as `.apkg`.

### Changed

- **HTML from imported Anki notes keeps its structure.** `<br>` and the ends of
  `<p>`, `<div>`, `<li>`, `<tr>`, `<h1>`–`<h6>` and `<blockquote>` become line
  breaks. List items are prefixed with `- `, indented two spaces per nesting level.
  Inline `<code>`/`<tt>` becomes `` `text` ``, and `<pre>` becomes a fenced code
  block. Entities are unescaped, and blank-line runs are capped at one. Table cells
  are joined with ` | `. Notes created by spacedrep are still returned verbatim.

### Fixed

- `deck import` refuses Anki's modern export format instead of importing its
  one-card "Please update to the latest Anki version" placeholder. A package that
  has `collection.anki21b` but no `collection.anki21`, or whose only note is that
  placeholder, fails with `import_error`: *this package is in the modern format;
  re-export from Anki Desktop with "Support older Anki versions" checked*. The
  working database is not touched.
- A package whose collection uses Anki's split-table schema is now refused with
  `unsupported_collection_format` before the working database is overwritten.
  Previously the check ran after the copy.
