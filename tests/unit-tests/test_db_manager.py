# tests/unit-tests/test_db_manager.py — DatabaseManager unit tests (store mocked).

from datetime import datetime

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

pytest.importorskip("pytestqt")

from opensak.db.manager import DatabaseManager, DatabaseInfo


@pytest.fixture
def manager(tmp_path, qapp, monkeypatch):
    """Isolated DatabaseManager: settings_store mocked, init_db no-op, tmp_path for files."""
    from opensak import settings_store as ss

    # Fresh in-memory store — no databases saved yet
    fresh = ss.SettingsStore()
    fresh._data = {}
    fresh._path = tmp_path / "opensak.json"
    monkeypatch.setattr(ss, "_store", fresh)

    with (
        patch("opensak.db.database.init_db"),
        patch("opensak.config.get_app_data_dir", return_value=tmp_path),
    ):
        yield DatabaseManager()


# ── Initialisation ────────────────────────────────────────────────────────────

class TestDatabaseManagerInit:
    def test_creates_default_database_when_settings_empty(self, manager):
        assert len(manager.databases) == 1

    def test_active_is_set_after_init(self, manager):
        assert manager.active is not None

    def test_active_path_matches_active_info(self, manager):
        assert manager.active_path == manager.active.path

    def test_databases_property_returns_copy(self, manager):
        dbs = manager.databases
        dbs.append(object())  # type: ignore
        assert len(manager.databases) == 1


# ── new_database ──────────────────────────────────────────────────────────────

class TestNewDatabase:
    def test_adds_entry_to_list(self, manager, tmp_path):
        with patch("opensak.db.database.init_db"):
            manager.new_database("Test", tmp_path / "Test.db")
        assert any(db.name == "Test" for db in manager.databases)

    def test_returns_database_info_instance(self, manager, tmp_path):
        with patch("opensak.db.database.init_db"):
            info = manager.new_database("Test2", tmp_path / "Test2.db")
        assert isinstance(info, DatabaseInfo)

    def test_increments_database_count(self, manager, tmp_path):
        before = len(manager.databases)
        with patch("opensak.db.database.init_db"):
            manager.new_database("Extra", tmp_path / "Extra.db")
        assert len(manager.databases) == before + 1

    def test_rejects_duplicate_name(self, manager, tmp_path):
        with patch("opensak.db.database.init_db"):
            manager.new_database("Dup", tmp_path / "Dup.db")
        with pytest.raises(ValueError):
            with patch("opensak.db.database.init_db"):
                manager.new_database("Dup", tmp_path / "Dup2.db")

    def test_two_new_databases_are_distinct(self, manager, tmp_path):
        with patch("opensak.db.database.init_db"):
            a = manager.new_database("A", tmp_path / "A.db")
            b = manager.new_database("B", tmp_path / "B.db")
        assert a.name != b.name


# ── rename ────────────────────────────────────────────────────────────────────

class TestRename:
    def test_renames_database(self, manager):
        db = manager.databases[0]
        manager.rename(db, "NewName")
        assert db.name == "NewName"

    def test_renamed_entry_visible_in_list(self, manager):
        db = manager.databases[0]
        manager.rename(db, "Visible")
        assert any(d.name == "Visible" for d in manager.databases)

    def test_rejects_name_already_taken_by_another(self, manager, tmp_path):
        with patch("opensak.db.database.init_db"):
            other = manager.new_database("Other", tmp_path / "Other.db")
        with pytest.raises(ValueError):
            manager.rename(manager.databases[0], "Other")

    def test_rename_to_same_name_is_allowed(self, manager):
        db = manager.databases[0]
        original = db.name
        manager.rename(db, original)
        assert db.name == original


# ── remove_from_list ──────────────────────────────────────────────────────────

class TestRemoveFromList:
    def test_removes_entry_from_list(self, manager, tmp_path):
        with patch("opensak.db.database.init_db"):
            extra = manager.new_database("Extra", tmp_path / "Extra.db")
        with patch("opensak.db.database.dispose_engine"):
            manager.remove_from_list(extra)
        assert extra not in manager.databases

    def test_file_is_not_deleted(self, manager, tmp_path):
        db_file = tmp_path / "Keep.db"
        db_file.touch()
        with patch("opensak.db.database.init_db"):
            extra = manager.new_database("Keep", db_file)
        with patch("opensak.db.database.dispose_engine"):
            manager.remove_from_list(extra)
        assert db_file.exists()

    def test_refuses_to_remove_active_database(self, manager):
        with pytest.raises(ValueError):
            with patch("opensak.db.database.dispose_engine"):
                manager.remove_from_list(manager.active)


# ── delete_database ───────────────────────────────────────────────────────────

class TestDeleteDatabase:
    def test_removes_entry_from_list(self, manager, tmp_path):
        db_file = tmp_path / "Del.db"
        db_file.touch()
        with patch("opensak.db.database.init_db"):
            extra = manager.new_database("Del", db_file)
        with patch("opensak.db.database.dispose_engine"):
            manager.delete_database(extra)
        assert extra not in manager.databases

    def test_deletes_file_from_disk(self, manager, tmp_path):
        db_file = tmp_path / "Gone.db"
        db_file.touch()
        with patch("opensak.db.database.init_db"):
            extra = manager.new_database("Gone", db_file)
        with patch("opensak.db.database.dispose_engine"):
            manager.delete_database(extra)
        assert not db_file.exists()

    def test_refuses_to_delete_active_database(self, manager):
        with pytest.raises(ValueError):
            with patch("opensak.db.database.dispose_engine"):
                manager.delete_database(manager.active)

    def test_missing_file_does_not_raise(self, manager, tmp_path):
        db_file = tmp_path / "Missing.db"
        with patch("opensak.db.database.init_db"):
            extra = manager.new_database("Missing", db_file)
        with patch("opensak.db.database.dispose_engine"):
            manager.delete_database(extra)  # file never existed


# ── open_database ─────────────────────────────────────────────────────────────

class TestOpenDatabase:
    def test_file_not_found_raises(self, manager, tmp_path):
        with pytest.raises(FileNotFoundError):
            manager.open_database(tmp_path / "nope.db")

    def test_opens_existing_file(self, manager, tmp_path):
        f = tmp_path / "Open.db"
        f.touch()
        info = manager.open_database(f)
        assert info.path == f

    def test_returns_existing_entry_for_same_path(self, manager, tmp_path):
        f = tmp_path / "Same.db"
        f.touch()
        a = manager.open_database(f)
        b = manager.open_database(f)
        assert a is b

    def test_dedupes_name_collision(self, manager, tmp_path):
        f1 = tmp_path / "Clash.db"
        f2 = tmp_path / "sub" / "Clash.db"
        f1.touch()
        f2.parent.mkdir()
        f2.touch()
        a = manager.open_database(f1)
        b = manager.open_database(f2)
        assert a.name != b.name


# ── switch_to ─────────────────────────────────────────────────────────────────

class TestSwitchTo:
    def test_switch_sets_active(self, manager, tmp_path):
        with patch("opensak.db.database.init_db"):
            extra = manager.new_database("Switch", tmp_path / "Switch.db")
        with patch("opensak.db.database.init_db"):
            manager.switch_to(extra)
        assert manager.active is extra


# ── copy_database ─────────────────────────────────────────────────────────────

class TestCopyDatabase:
    def test_copies_file_and_adds_entry(self, manager, tmp_path):
        src = tmp_path / "Src.db"
        src.touch()
        with patch("opensak.db.database.init_db"):
            manager.new_database("Src", src)
        src_info = manager.databases[-1]
        dst = tmp_path / "Dst.db"
        copy = manager.copy_database(src_info, "Dst", dst)
        assert copy.name == "Dst"
        assert dst.exists()

    def test_default_path_uses_app_data_dir(self, manager, tmp_path):
        src = tmp_path / "Src2.db"
        src.touch()
        with patch("opensak.db.database.init_db"):
            manager.new_database("Src2", src)
        src_info = manager.databases[-1]
        with patch("opensak.settings_store.get_db_dir", return_value=tmp_path):
            copy = manager.copy_database(src_info, "DstDefault")
        assert copy.path.parent == tmp_path

    def test_rejects_duplicate_name(self, manager, tmp_path):
        src = tmp_path / "CopySrc.db"
        src.touch()
        with patch("opensak.db.database.init_db"):
            manager.new_database("CopySrc", src)
        src_info = manager.databases[-1]
        with pytest.raises(ValueError):
            manager.copy_database(src_info, "CopySrc")


# ── ensure_active_initialised ─────────────────────────────────────────────────

class TestEnsureActiveInitialised:
    def test_initialises_active(self, manager):
        with patch("opensak.db.database.init_db") as mock_init:
            manager.ensure_active_initialised()
        mock_init.assert_called_once_with(db_path=manager.active.path)
