import json
import stat
import sys

from nrgrd.config.config import Config
from nrgrd.config.credentials import FileStore, migrate_plaintext_api_key
from tests.helpers import MemoryStore


def test_file_store_round_trips_the_key(tmp_path):
    store = FileStore(tmp_path / "credentials.json")

    assert store.get() == ""
    store.set("a-secret")
    assert store.get() == "a-secret"

    store.delete()
    assert store.get() == ""


def test_file_store_is_not_world_readable(tmp_path):
    if sys.platform.startswith("win"):
        return

    path = tmp_path / "credentials.json"
    FileStore(path).set("a-secret")

    mode = stat.S_IMODE(path.stat().st_mode)
    assert not mode & stat.S_IRGRP
    assert not mode & stat.S_IROTH


def test_file_store_survives_a_corrupt_file(tmp_path):
    path = tmp_path / "credentials.json"
    path.write_text("not json at all", encoding="utf-8")

    assert FileStore(path).get() == ""


def test_plaintext_key_moves_out_of_the_config_file(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(
        "nrgrd.config.credentials.save_config",
        lambda config: config_path.write_text(
            config.model_dump_json(indent=4), encoding="utf-8"
        ),
    )

    config = Config(api_key="legacy-key", base_url="https://x/v1", model="m")
    store = MemoryStore()

    assert migrate_plaintext_api_key(config, store) is True
    assert store.get() == "legacy-key"
    assert config.api_key == ""
    # The key must be gone from what gets written back to disk.
    assert json.loads(config_path.read_text())["api_key"] == ""


def test_migration_is_a_no_op_when_there_is_nothing_to_move():
    config = Config(api_key="", base_url="https://x/v1", model="m")
    store = MemoryStore()

    assert migrate_plaintext_api_key(config, store) is False
    assert store.get() == ""
