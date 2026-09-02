import itertools

from rich.console import Console

import nrgrd.screens.connect as connect
from nrgrd.api.provider import ProviderError
from nrgrd.config.config import Config
from tests.helpers import MemoryStore


def quiet_console() -> Console:
    return Console(file=open("/dev/null", "w"), force_terminal=False)


def answer_with(monkeypatch, answers):
    """Feed the screen a scripted sequence of prompt answers."""
    supply = itertools.chain(answers)
    monkeypatch.setattr(
        connect.Prompt, "ask", staticmethod(lambda *a, **k: next(supply))
    )


def stub_models(monkeypatch, models=None, error=None):
    def list_models(self):
        if error is not None:
            raise error
        return models or []

    monkeypatch.setattr(connect.OpenAICompatibleProvider, "list_models", list_models)


def test_completed_screen_saves_endpoint_model_and_key(monkeypatch, tmp_path):
    saved = {}
    monkeypatch.setattr(connect, "save_config", lambda config: saved.update(config.model_dump()))
    stub_models(monkeypatch, ["llama-3.1-8b", "qwen3-coder"])
    answer_with(monkeypatch, ["https://deployment.example/v1", "the-key", "2"])

    config = Config()
    store = MemoryStore()

    result = connect.run_connect_screen(quiet_console(), config, store)

    assert result == "the-key"
    assert config.base_url == "https://deployment.example/v1"
    # "2" picked the second listed model.
    assert config.model == "qwen3-coder"
    # The key goes to the store, never to the config file.
    assert store.get() == "the-key"
    assert config.api_key == ""
    assert saved["api_key"] == ""


def test_model_can_be_chosen_by_name(monkeypatch):
    monkeypatch.setattr(connect, "save_config", lambda config: None)
    stub_models(monkeypatch, ["a-model", "b-model"])
    answer_with(monkeypatch, ["https://x/v1", "k", "b-model"])

    config = Config()
    connect.run_connect_screen(quiet_console(), config, MemoryStore())

    assert config.model == "b-model"


def test_unreachable_endpoint_still_lets_the_user_continue(monkeypatch):
    """A dead endpoint must not trap the user in the screen."""
    monkeypatch.setattr(connect, "save_config", lambda config: None)
    stub_models(
        monkeypatch,
        error=ProviderError("Could not reach the endpoint.", "Endpoint: x", "Check it."),
    )
    answer_with(monkeypatch, ["https://down.example/v1", "k", "typed-by-hand"])

    config = Config()
    store = MemoryStore()

    result = connect.run_connect_screen(quiet_console(), config, store)

    assert result == "k"
    assert config.model == "typed-by-hand"


def test_empty_key_keeps_the_stored_one(monkeypatch):
    monkeypatch.setattr(connect, "save_config", lambda config: None)
    stub_models(monkeypatch, ["m"])
    answer_with(monkeypatch, ["https://x/v1", "", "m"])

    store = MemoryStore()
    store.set("existing-key")

    result = connect.run_connect_screen(
        quiet_console(), Config(), store, current_api_key="existing-key"
    )

    assert result == "existing-key"


def test_missing_key_aborts_without_saving(monkeypatch):
    saves = []
    monkeypatch.setattr(connect, "save_config", lambda config: saves.append(config))
    answer_with(monkeypatch, ["https://x/v1", ""])

    store = MemoryStore()
    result = connect.run_connect_screen(quiet_console(), Config(), store)

    assert result is None
    assert saves == []
    assert store.get() == ""


def test_cancelling_aborts_without_saving(monkeypatch):
    saves = []
    monkeypatch.setattr(connect, "save_config", lambda config: saves.append(config))

    def cancel(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(connect.Prompt, "ask", staticmethod(cancel))

    result = connect.run_connect_screen(quiet_console(), Config(), MemoryStore())

    assert result is None
    assert saves == []
