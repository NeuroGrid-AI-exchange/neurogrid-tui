"""Regression tests for TUI and CLI defects found in the pre-release audit."""

import io

import pytest
import rich.live
from rich.console import Console

import nrgrd.app as app_module
from nrgrd.api.provider import ProviderError
from tests.helpers import MemoryStore


@pytest.fixture
def app(tmp_path, monkeypatch):
    """An NrgrdApp that touches no real config, keyring, or session data."""
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    monkeypatch.setattr("nrgrd.config.config.user_config_dir", lambda **kw: str(config_dir))
    monkeypatch.setattr("nrgrd.system.prompt.user_config_dir", lambda **kw: str(config_dir))
    monkeypatch.setattr("nrgrd.sessions.store.user_data_dir", lambda **kw: str(data_dir))
    monkeypatch.setattr(app_module, "load_credential_store", MemoryStore)

    instance = app_module.NrgrdApp()
    instance.console = Console(file=io.StringIO(), force_terminal=False, width=100)
    instance.config.model = "test-model"
    return instance


# --- CLI exit codes -------------------------------------------------------


def test_cli_exits_zero_when_the_agent_finishes(app, fake_provider, delta):
    app.provider = fake_provider([[delta(content="All good.")]])

    assert app.run_once("hello") == 0


def test_cli_exits_non_zero_when_the_request_fails(app, fake_provider):
    """Scripts and CI must be able to tell a failed run from a good one."""

    class Unreachable(fake_provider):
        def stream_chat(self, model, messages, tools=None):
            raise ProviderError("Could not reach the endpoint.", "Endpoint: x", "Check it.")
            yield  # pragma: no cover - generator marker

    app.provider = Unreachable([])

    assert app.run_once("hello") == 1


def test_cli_exits_130_when_interrupted(app, fake_provider, delta):
    class Interrupted(fake_provider):
        def stream_chat(self, model, messages, tools=None):
            yield delta(content="partial")
            raise KeyboardInterrupt

    app.provider = Interrupted([])

    assert app.run_once("hello") == 130


def test_cli_exits_non_zero_without_a_model(app, fake_provider, delta):
    app.provider = fake_provider([[delta(content="unused")]])
    app.config.model = ""

    assert app.run_once("hello") == 1


# --- permission prompt ----------------------------------------------------


@pytest.mark.parametrize("arguments", ["[1, 2]", '"just a string"', "42", "not json"])
def test_permission_prompt_survives_arguments_that_are_not_an_object(app, arguments):
    app.approve_all = False
    # No terminal in tests, so the prompt denies; it must not crash first.
    assert app.ask_permission("shell", arguments) == "no"


def test_live_display_is_stopped_before_asking_permission(app, fake_provider, delta, monkeypatch):
    """A refreshing stream panel used to draw over the permission prompt."""
    running = {"count": 0}
    original_start, original_stop = rich.live.Live.start, rich.live.Live.stop

    def start(self, *args, **kwargs):
        running["count"] += 1
        return original_start(self, *args, **kwargs)

    def stop(self, *args, **kwargs):
        if self._started:
            running["count"] -= 1
        return original_stop(self, *args, **kwargs)

    monkeypatch.setattr(rich.live.Live, "start", start)
    monkeypatch.setattr(rich.live.Live, "stop", stop)

    live_at_prompt: list[int] = []
    app.permissions.callback = lambda name, args: live_at_prompt.append(running["count"]) or "no"
    app.provider = fake_provider(
        [
            [
                delta(content="I will run a command"),
                delta(tool_name="shell", tool_args='{"command": "ls"}', tool_id="c1"),
            ],
            [delta(content="ok")],
        ]
    )

    app.run_coding_agent([{"role": "user", "content": "x"}])

    assert live_at_prompt == [0]


# --- input ----------------------------------------------------------------


def test_prompt_session_is_reused_so_history_survives(app, monkeypatch):
    created: list[object] = []

    class FakeSession:
        def __init__(self, **kwargs):
            created.append(self)

        def prompt(self, *args, **kwargs):
            return "typed"

    monkeypatch.setattr(app_module, "PromptSession", FakeSession)
    monkeypatch.setattr(app_module, "WordCompleter", lambda *a, **k: None)

    app.ask_for_input()
    app.ask_for_input()

    assert len(created) == 1
