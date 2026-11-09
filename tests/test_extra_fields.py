"""Extra note fields on the write path (card add/update --field, bulk extra_fields)."""

import json
import sqlite3
from pathlib import Path

import pytest

from spacedrep import core, db
from spacedrep.anki_schema import (
    _BASIC_MODEL,  # pyright: ignore[reportPrivateUsage]
    BASIC_MODEL_ID,
    BASIC_REVERSED_MODEL_ID,
    basic_guid,
)
from spacedrep.models import BulkCardInput


def _model(db_path: Path, mid: int) -> dict[str, object]:
    conn = sqlite3.connect(str(db_path))
    try:
        models = json.loads(conn.execute("SELECT models FROM col").fetchone()[0])
    finally:
        conn.close()
    model: dict[str, object] = models[str(mid)]
    return model


def _field_names(db_path: Path, mid: int) -> list[str]:
    flds = _model(db_path, mid)["flds"]
    assert isinstance(flds, list)
    return [str(f["name"]) for f in flds]  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]


def _flds(db_path: Path, card_id: int) -> list[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT n.flds FROM notes n JOIN cards c ON c.nid = n.id WHERE c.id = ?", (card_id,)
        ).fetchone()
    finally:
        conn.close()
    return str(row[0]).split("\x1f")


def _add(db_path: Path, q: str = "Q", a: str = "A", **extras: str) -> int:
    return int(core.add_card(db_path, q, a, deck="D", extra_fields=extras or None)["card_id"])


class TestAddWithFields:
    def test_extras_round_trip_through_get_and_next(self, tmp_db: Path) -> None:
        card_id = _add(tmp_db, Source="SICP 1.2", Example="(square 3)")
        detail = core.get_card_detail(tmp_db, card_id)
        assert detail.extra_fields == {"Source": "SICP 1.2", "Example": "(square 3)"}
        assert (detail.question, detail.answer) == ("Q", "A")
        due = core.get_next_card(tmp_db)
        assert due is not None
        assert due.extra_fields == {"Source": "SICP 1.2", "Example": "(square 3)"}

    def test_model_grows_and_answer_template_shows_field(self, tmp_db: Path) -> None:
        _add(tmp_db, Source="x")
        assert _field_names(tmp_db, BASIC_MODEL_ID) == ["Question", "Answer", "Source"]
        tmpls = _model(tmp_db, BASIC_MODEL_ID)["tmpls"]
        assert isinstance(tmpls, list)
        afmt = str(tmpls[0]["afmt"])  # pyright: ignore[reportUnknownArgumentType]
        assert afmt.endswith('{{#Source}}<div class="Source">{{Source}}</div>{{/Source}}')
        assert afmt.startswith('{{FrontSide}}<hr id="answer">{{Answer}}')

    def test_fields_never_reordered(self, tmp_db: Path) -> None:
        _add(tmp_db, "Q1", Source="x")
        _add(tmp_db, "Q2", Example="y", Source="z")
        assert _field_names(tmp_db, BASIC_MODEL_ID) == ["Question", "Answer", "Source", "Example"]

    def test_module_default_model_not_mutated(self, tmp_db: Path) -> None:
        _add(tmp_db, Source="x")
        assert [f["name"] for f in _BASIC_MODEL["flds"]] == ["Question", "Answer"]

    def test_note_padded_to_model_length(self, tmp_db: Path) -> None:
        _add(tmp_db, "Q1", Source="s", Example="e")
        card_id = _add(tmp_db, "Q2", Example="only")
        assert _flds(tmp_db, card_id) == ["Q2", "A", "", "only"]

    def test_notes_without_extras_stay_two_fields(self, tmp_db: Path) -> None:
        _add(tmp_db, "Q1", Source="s")
        card_id = _add(tmp_db, "Q2")
        assert _flds(tmp_db, card_id) == ["Q2", "A"]
        assert core.get_card_detail(tmp_db, card_id).extra_fields == {}

    def test_empty_value_allowed(self, tmp_db: Path) -> None:
        card_id = _add(tmp_db, Source="")
        assert "Source" in _field_names(tmp_db, BASIC_MODEL_ID)
        assert core.get_card_detail(tmp_db, card_id).extra_fields == {}

    def test_extras_are_plain_text(self, tmp_db: Path) -> None:
        card_id = _add(tmp_db, Example="<b>List<int></b> &lt;")
        assert core.get_card_detail(tmp_db, card_id).extra_fields == {
            "Example": "<b>List<int></b> &lt;"
        }

    def test_readd_keeps_extras_and_merges(self, tmp_db: Path) -> None:
        card_id = _add(tmp_db, Source="s", Example="e")
        again = core.add_card(tmp_db, "Q", "A2", deck="D", extra_fields={"Example": "e2"})
        assert again["card_id"] == card_id and again["was_update"] is True
        detail = core.get_card_detail(tmp_db, card_id)
        assert detail.answer == "A2"
        assert detail.extra_fields == {"Source": "s", "Example": "e2"}
        core.add_card(tmp_db, "Q", "A3", deck="D")
        assert core.get_card_detail(tmp_db, card_id).extra_fields == {
            "Source": "s",
            "Example": "e2",
        }

    def test_dedup_guid_unchanged(self, tmp_db: Path) -> None:
        _add(tmp_db, Source="s")
        conn = sqlite3.connect(str(tmp_db))
        guid = conn.execute("SELECT guid FROM notes").fetchone()[0]
        conn.close()
        assert guid == basic_guid("Q", "D")

    def test_add_result_shape_unchanged(self, tmp_db: Path) -> None:
        result = core.add_card(tmp_db, "Q", "A", deck="D", extra_fields={"Source": "s"})
        assert set(result) == {"card_id", "deck", "was_update"}

    @pytest.mark.parametrize(
        "name",
        ["", "has space", "tab\there", "a\x1fb", "{x", "x}", "a:b", 'q"', "#x", "/x", "^x", "Tags"],
    )
    def test_invalid_names_rejected(self, tmp_db: Path, name: str) -> None:
        with pytest.raises(core.InvalidFieldError) as exc:
            core.add_card(tmp_db, "Q", "A", extra_fields={name: "v"})
        assert exc.value.error_code == "invalid_field"
        assert exc.value.exit_code == 2
        assert core.list_cards(tmp_db).total == 0
        assert _field_names(tmp_db, BASIC_MODEL_ID) == ["Question", "Answer"]

    @pytest.mark.parametrize("name", ["Question", "Answer"])
    def test_question_answer_names_rejected(self, tmp_db: Path, name: str) -> None:
        with pytest.raises(core.InvalidFieldError, match=r"set it with the \w+ argument"):
            core.add_card(tmp_db, "Q", "A", extra_fields={name: "v"})

    def test_case_clash_rejected(self, tmp_db: Path) -> None:
        _add(tmp_db, "Q1", Source="s")
        with pytest.raises(core.InvalidFieldError) as exc:
            _add(tmp_db, "Q2", source="s")
        assert "'Source'" in exc.value.suggestion

    def test_cross_model_collision_still_raised(self, tmp_db: Path) -> None:
        core.add_reversed_card(tmp_db, "Q", "A", deck="D")
        with pytest.raises(core.CrossModelCollisionError):
            _add(tmp_db, Source="s")


class TestReversedWithFields:
    def test_both_cards_show_extras(self, tmp_db: Path) -> None:
        r = core.add_reversed_card(tmp_db, "chat", "cat", deck="fr", extra_fields={"Gender": "m"})
        fwd = core.get_card_detail(tmp_db, r.card_ids[0])
        rev = core.get_card_detail(tmp_db, r.card_ids[1])
        assert (fwd.question, fwd.answer, fwd.extra_fields) == ("chat", "cat", {"Gender": "m"})
        assert (rev.question, rev.answer, rev.extra_fields) == ("cat", "chat", {"Gender": "m"})

    def test_both_templates_grow(self, tmp_db: Path) -> None:
        core.add_reversed_card(tmp_db, "chat", "cat", extra_fields={"Gender": "m"})
        assert _field_names(tmp_db, BASIC_REVERSED_MODEL_ID) == ["Question", "Answer", "Gender"]
        tmpls = _model(tmp_db, BASIC_REVERSED_MODEL_ID)["tmpls"]
        assert isinstance(tmpls, list)
        for tmpl in tmpls:  # pyright: ignore[reportUnknownVariableType]
            assert "{{#Gender}}" in str(tmpl["afmt"])  # pyright: ignore[reportUnknownArgumentType]
        # Basic model untouched.
        assert _field_names(tmp_db, BASIC_MODEL_ID) == ["Question", "Answer"]


class TestUpdateFields:
    def test_change_one_clear_another(self, tmp_db: Path) -> None:
        card_id = _add(tmp_db, Source="s", Example="e")
        detail = core.update_card(tmp_db, card_id, fields={"Source": "s2", "Example": ""})
        assert detail.extra_fields == {"Source": "s2"}
        assert (detail.question, detail.answer) == ("Q", "A")

    def test_update_grows_own_model(self, tmp_db: Path) -> None:
        card_id = _add(tmp_db)
        detail = core.update_card(tmp_db, card_id, fields={"Mnemonic": "m"})
        assert detail.extra_fields == {"Mnemonic": "m"}
        assert _field_names(tmp_db, BASIC_MODEL_ID) == ["Question", "Answer", "Mnemonic"]
        assert _flds(tmp_db, card_id) == ["Q", "A", "m"]

    def test_update_pads_short_note(self, tmp_db: Path) -> None:
        old = _add(tmp_db, "Q1")
        _add(tmp_db, "Q2", Source="s", Example="e")
        core.update_card(tmp_db, old, fields={"Example": "x"})
        assert _flds(tmp_db, old) == ["Q1", "A", "", "x"]

    def test_update_combined_with_answer(self, tmp_db: Path) -> None:
        card_id = _add(tmp_db, Source="s")
        detail = core.update_card(tmp_db, card_id, answer="A2", fields={"Source": "t"})
        assert (detail.answer, detail.extra_fields) == ("A2", {"Source": "t"})

    @pytest.mark.parametrize("name", ["Question", "Answer"])
    def test_question_answer_field_rejected(self, tmp_db: Path, name: str) -> None:
        card_id = _add(tmp_db)
        with pytest.raises(core.InvalidFieldError) as exc:
            core.update_card(tmp_db, card_id, fields={name: "x"})
        assert "--question / --answer" in exc.value.message
        assert core.get_card_detail(tmp_db, card_id).question == "Q"

    def test_reversed_card_two_protects_both_sides(self, tmp_db: Path) -> None:
        r = core.add_reversed_card(tmp_db, "chat", "cat")
        for name in ("Question", "Answer"):
            with pytest.raises(core.InvalidFieldError):
                core.update_card(tmp_db, r.card_ids[1], fields={name: "x"})
        detail = core.update_card(tmp_db, r.card_ids[1], fields={"Gender": "m"})
        assert detail.extra_fields == {"Gender": "m"}
        assert core.get_card_detail(tmp_db, r.card_ids[0]).extra_fields == {"Gender": "m"}

    def test_invalid_new_name_changes_nothing(self, tmp_db: Path) -> None:
        card_id = _add(tmp_db, Source="s")
        with pytest.raises(core.InvalidFieldError):
            core.update_card(tmp_db, card_id, answer="changed", fields={"bad name": "x"})
        detail = core.get_card_detail(tmp_db, card_id)
        assert (detail.answer, detail.extra_fields) == ("A", {"Source": "s"})

    def test_separator_in_value_rejected(self, tmp_db: Path) -> None:
        card_id = _add(tmp_db, Source="s")
        with pytest.raises(core.InvalidFieldError, match="separator"):
            core.update_card(tmp_db, card_id, fields={"Source": "a\x1fb"})
        with pytest.raises(core.InvalidFieldError, match="separator"):
            _add(tmp_db, "Q2", Source="a\x1fb")
        assert _flds(tmp_db, card_id) == ["Q", "A", "s"]

    def test_card_not_found(self, tmp_db: Path) -> None:
        with pytest.raises(core.CardNotFoundError):
            core.update_card(tmp_db, 999, fields={"Source": "s"})


class TestImportedModelFields:
    def test_set_and_clear_existing_field(self, tmp_db: Path, notes_field_apkg: Path) -> None:
        core.open_deck(tmp_db, notes_field_apkg, force=True)
        assert core.get_card_detail(tmp_db, 30).extra_fields == {"Notes": "old note"}
        detail = core.update_card(tmp_db, 30, fields={"Notes": "<b>new</b> note"})
        assert detail.extra_fields == {"Notes": "new note"}
        assert core.update_card(tmp_db, 30, fields={"Notes": ""}).extra_fields == {}

    def test_unknown_field_lists_model_fields(self, tmp_db: Path, notes_field_apkg: Path) -> None:
        core.open_deck(tmp_db, notes_field_apkg, force=True)
        with pytest.raises(core.InvalidFieldError) as exc:
            core.update_card(tmp_db, 30, fields={"Source": "x"})
        assert "Basic+Notes" in exc.value.message
        assert "Front, Back, Notes" in exc.value.message
        assert exc.value.extra["available_fields"] == "Front, Back, Notes"
        assert _field_names(tmp_db, 4000) == ["Front", "Back", "Notes"]

    def test_name_match_is_case_sensitive(self, tmp_db: Path, notes_field_apkg: Path) -> None:
        core.open_deck(tmp_db, notes_field_apkg, force=True)
        with pytest.raises(core.InvalidFieldError, match="Unknown field 'notes'"):
            core.update_card(tmp_db, 30, fields={"notes": "x"})

    def test_front_back_rejected(self, tmp_db: Path, notes_field_apkg: Path) -> None:
        core.open_deck(tmp_db, notes_field_apkg, force=True)
        for name in ("Front", "Back"):
            with pytest.raises(core.InvalidFieldError, match="renders as this card"):
                core.update_card(tmp_db, 30, fields={name: "x"})

    def test_imported_cloze_extra(self, tmp_db: Path, cloze_apkg: Path) -> None:
        core.open_deck(tmp_db, cloze_apkg, force=True)
        card_id = core.list_cards(tmp_db).cards[0].card_id
        detail = core.update_card(tmp_db, card_id, fields={"Extra": "hint"})
        assert detail.extra_fields.get("Extra") == "hint"
        with pytest.raises(core.InvalidFieldError, match="cloze text"):
            core.update_card(tmp_db, card_id, fields={"Text": "x"})


class TestClozeFields:
    def test_back_extra_survives_update_cloze(self, tmp_db: Path) -> None:
        r = core.add_cloze_note(tmp_db, "{{c1::Ottawa}} is a capital")
        core.update_card(tmp_db, r.card_ids[0], fields={"Back Extra": "Canada"})
        core.update_cloze_note(tmp_db, r.card_ids[0], "{{c1::Ottawa}} is the capital")
        assert core.get_card_detail(tmp_db, r.card_ids[0]).extra_fields == {"Back Extra": "Canada"}

    def test_own_cloze_model_does_not_grow(self, tmp_db: Path) -> None:
        r = core.add_cloze_note(tmp_db, "{{c1::Ottawa}} is a capital")
        with pytest.raises(core.InvalidFieldError, match="Text, Back Extra"):
            core.update_card(tmp_db, r.card_ids[0], fields={"Source": "x"})


class TestBulkFields:
    def test_basic_and_reversed_extras(self, tmp_db: Path) -> None:
        cards = [
            BulkCardInput(question="Q1", answer="A1", extra_fields={"Source": "s1"}),
            BulkCardInput(
                question="chat", answer="cat", type="reversed", extra_fields={"Gender": "m"}
            ),
            BulkCardInput(question="Q2", answer="A2"),
        ]
        result = core.add_cards_bulk(tmp_db, cards)
        assert result.total == 4
        details = [core.get_card_detail(tmp_db, cid) for cid in result.created]
        assert [d.extra_fields for d in details] == [
            {"Source": "s1"},
            {"Gender": "m"},
            {"Gender": "m"},
            {},
        ]

    def test_cloze_with_extras_rejected(self) -> None:
        with pytest.raises(ValueError, match="extra_fields is not supported for cloze"):
            BulkCardInput(question="{{c1::x}}", type="cloze", extra_fields={"Source": "s"})

    def test_cloze_with_empty_extras_ok(self) -> None:
        BulkCardInput(question="{{c1::x}}", type="cloze", extra_fields={})

    def test_invalid_name_aborts_batch_with_index(self, tmp_db: Path) -> None:
        cards = [
            BulkCardInput(question="Q1", answer="A1"),
            BulkCardInput(question="Q2", answer="A2", extra_fields={"bad name": "x"}),
        ]
        with pytest.raises(core.InvalidFieldError) as exc:
            core.add_cards_bulk(tmp_db, cards)
        assert exc.value.extra["batch_index"] == 1
        assert core.list_cards(tmp_db).total == 0


class TestExportImportRoundTrip:
    def test_extras_survive_apkg_round_trip(self, tmp_db: Path, tmp_path: Path) -> None:
        card_id = _add(tmp_db, Source="s", Example="e")
        out = tmp_path / "out.apkg"
        core.save_deck(tmp_db, out)
        target = tmp_path / "imported.anki21"
        core.open_deck(target, out, force=True)
        db.clear_all_model_caches()
        detail = core.get_card_detail(target, card_id)
        assert detail.extra_fields == {"Source": "s", "Example": "e"}
        # Still spacedrep's own model: update can grow it further.
        grown = core.update_card(target, card_id, fields={"Mnemonic": "m"})
        assert grown.extra_fields == {"Source": "s", "Example": "e", "Mnemonic": "m"}


class TestParseFieldOptions:
    def test_split_on_first_equals(self) -> None:
        assert core.parse_field_options(["Expr=a=b", "Empty="]) == {"Expr": "a=b", "Empty": ""}

    def test_none(self) -> None:
        assert core.parse_field_options(None) == {}

    def test_missing_equals(self) -> None:
        with pytest.raises(core.InvalidFieldError, match="NAME=VALUE"):
            core.parse_field_options(["Source"])

    def test_duplicate_name(self) -> None:
        with pytest.raises(core.InvalidFieldError, match="more than once"):
            core.parse_field_options(["A=1", "A=2"])
