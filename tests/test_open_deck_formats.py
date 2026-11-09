"""deck import refuses modern Anki packages and accepts .colpkg."""

import shutil
import sqlite3
import zipfile
from pathlib import Path

import pytest

from spacedrep import core

MODERN_MESSAGE = (
    "This package is in the modern format; re-export from Anki Desktop with "
    '"Support older Anki versions" checked.'
)


def _zip(path: Path, members: dict[str, Path | bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, src in members.items():
            if isinstance(src, Path):
                zf.write(src, name)
            else:
                zf.writestr(name, src)
    return path


def _snapshot(db_path: Path) -> list[tuple[object, ...]]:
    conn = sqlite3.connect(str(db_path))
    try:
        return [tuple(r) for r in conn.execute("SELECT id, flds FROM notes ORDER BY id")]
    finally:
        conn.close()


@pytest.fixture
def db_with_card(tmp_db: Path) -> Path:
    core.add_card(tmp_db, "Keep me", "please", deck="D")
    return tmp_db


class TestModernPackageRefused:
    def test_anki21b_with_stub(
        self, db_with_card: Path, legacy_stub_db: Path, tmp_path: Path
    ) -> None:
        pkg = _zip(
            tmp_path / "modern.apkg",
            {
                "collection.anki21b": b"\x28\xb5\x2f\xfd zstd payload",
                "collection.anki2": legacy_stub_db,
                "media": b"\x28\xb5\x2f\xfd",
            },
        )
        before = _snapshot(db_with_card)
        with pytest.raises(core.ApkgImportError) as exc:
            core.open_deck(db_with_card, pkg, force=True)
        assert exc.value.error_code == "import_error"
        assert exc.value.exit_code == 1
        assert exc.value.message == MODERN_MESSAGE
        assert _snapshot(db_with_card) == before

    def test_stub_only(self, db_with_card: Path, legacy_stub_db: Path, tmp_path: Path) -> None:
        pkg = _zip(tmp_path / "stub.apkg", {"collection.anki2": legacy_stub_db, "media": b"{}"})
        before = _snapshot(db_with_card)
        with pytest.raises(core.ApkgImportError) as exc:
            core.open_deck(db_with_card, pkg, force=True)
        assert exc.value.message == MODERN_MESSAGE
        assert _snapshot(db_with_card) == before

    def test_new_db_path_not_created(self, legacy_stub_db: Path, tmp_path: Path) -> None:
        pkg = _zip(tmp_path / "stub.apkg", {"collection.anki2": legacy_stub_db})
        target = tmp_path / "fresh.anki21"
        with pytest.raises(core.ApkgImportError):
            core.open_deck(target, pkg)
        assert not target.exists()

    def test_anki21_preferred_over_anki21b(self, tmp_db: Path, tmp_path: Path) -> None:
        src = tmp_path / "src.anki21"
        core.init_database(src)
        core.add_card(src, "Real", "card", deck="D")
        pkg = _zip(
            tmp_path / "both.apkg",
            {"collection.anki21": src, "collection.anki21b": b"zstd"},
        )
        result = core.open_deck(tmp_db, pkg, force=True)
        assert result.card_count == 1

    def test_cli_error_json(self, db_with_card: Path, legacy_stub_db: Path, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from spacedrep.cli import app

        pkg = _zip(tmp_path / "stub.apkg", {"collection.anki2": legacy_stub_db})
        result = CliRunner().invoke(
            app, ["deck", "import", str(pkg), "--force", "--db", str(db_with_card)]
        )
        assert result.exit_code == 1
        assert '"error": "import_error"' in result.output
        assert "modern format" in result.output


class TestColpkg:
    def test_colpkg_suffix_accepted(self, tmp_db: Path, cloze_apkg: Path, tmp_path: Path) -> None:
        colpkg = tmp_path / "collection.colpkg"
        shutil.copy(cloze_apkg, colpkg)
        result = core.open_deck(tmp_db, colpkg, force=True)
        assert result.card_count == 2

    def test_other_suffix_still_rejected(self, tmp_db: Path, tmp_path: Path) -> None:
        bad = tmp_path / "deck.zip"
        bad.write_bytes(b"")
        with pytest.raises(core.ApkgImportError, match=r"Expected \.apkg file"):
            core.open_deck(tmp_db, bad, force=True)
