from pathlib import Path

import pytest

from nrgrd.sessions import DEFAULT_SESSION, SessionManager
from nrgrd.sessions.store import slugify


@pytest.fixture
def manager(tmp_path, monkeypatch):
    """A session manager whose storage lives in a temporary directory."""
    monkeypatch.setattr(
        "nrgrd.sessions.store.user_data_dir", lambda **kwargs: str(tmp_path)
    )
    return SessionManager(Path.cwd())


def test_starts_on_the_default_session(manager):
    assert manager.name == DEFAULT_SESSION


def test_a_new_session_is_listed_even_while_empty(manager):
    """Naming a session must make it real, not wait for a first message."""
    manager.start("auth-fix")

    names = [session.name for session in manager.list_sessions()]
    assert "auth-fix" in names


def test_sessions_keep_separate_conversations(manager):
    manager.start("first")
    manager.add_message("user", "belongs to first")

    manager.start("second")
    manager.add_message("user", "belongs to second")

    assert [m.content for m in manager.get_messages()] == ["belongs to second"]
    manager.switch("first")
    assert [m.content for m in manager.get_messages()] == ["belongs to first"]


def test_resuming_restores_the_conversation(manager):
    manager.start("work")
    manager.add_message("user", "remember me")
    manager.switch(DEFAULT_SESSION)

    manager.switch("work")

    assert [m.content for m in manager.get_messages()] == ["remember me"]


def test_rename_moves_the_conversation(manager):
    manager.start("old-name")
    manager.add_message("user", "kept")

    assert manager.rename("new-name") is True

    names = [session.name for session in manager.list_sessions()]
    assert "new-name" in names
    assert "old-name" not in names
    assert [m.content for m in manager.get_messages()] == ["kept"]


def test_rename_refuses_to_clobber_an_existing_session(manager):
    manager.start("keep-me")
    manager.add_message("user", "precious")
    manager.start("other")

    assert manager.rename("keep-me") is False
    # The original conversation must be intact.
    manager.switch("keep-me")
    assert [m.content for m in manager.get_messages()] == ["precious"]


def test_delete_removes_a_session(manager):
    manager.start("temporary")
    assert manager.delete("temporary") is True
    assert "temporary" not in [s.name for s in manager.list_sessions()]


def test_deleting_the_active_session_falls_back_to_default(manager):
    manager.start("active")
    manager.delete("active")
    assert manager.name == DEFAULT_SESSION


def test_deleting_an_unknown_session_reports_failure(manager):
    assert manager.delete("never-existed") is False


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Auth Fix", "auth-fix"),
        ("../../escape", "escape"),
        ("with/slash", "with-slash"),
        ("   ", DEFAULT_SESSION),
    ],
)
def test_names_are_reduced_to_safe_filenames(name, expected):
    assert slugify(name) == expected
