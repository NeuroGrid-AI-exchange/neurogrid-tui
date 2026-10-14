"""The context figures count what is really sent, and long replies keep scrolling."""

import io

import pytest
from rich.console import Console
from rich.text import Text

import nrgrd.app as app_module
from nrgrd.api import OpenAICompatibleProvider
from nrgrd.context.tokens import estimate_request_tokens
from nrgrd.widgets.stream import StreamTail
from tests.helpers import MemoryStore


@pytest.fixture
def app(tmp_path, monkeypatch):
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


# --- token estimate -------------------------------------------------------


def test_request_estimate_counts_tools_and_tool_calls():
    messages = [{"role": "user", "content": "x" * 400}]
    bare = estimate_request_tokens(messages)

    with_tools = estimate_request_tokens(
        messages, [{"type": "function", "function": {"name": "read", "parameters": {"a": "b" * 400}}}]
    )
    with_call = estimate_request_tokens(
        messages
        + [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"function": {"name": "read", "arguments": "y" * 400}}],
            }
        ]
    )

    assert bare == 104
    assert with_tools > bare + 100
    assert with_call > bare + 100


# --- context window from the endpoint -------------------------------------


class Models:
    def __init__(self, data=None, error=None):
        self.data = data or []
        self.error = error
        self.calls = 0

    def list(self):
        self.calls += 1
        if self.error:
            raise self.error
        return type("Response", (), {"data": self.data})()


class Client:
    def __init__(self, models):
        self.models = models


class Item:
    def __init__(self, id, **extra):
        self.id = id
        for key, value in extra.items():
            setattr(self, key, value)


@pytest.mark.parametrize(
    "field", ["max_model_len", "context_length", "max_context_length", "context_window"]
)
def test_context_window_is_read_from_the_models_list(field):
    models = Models([Item("small"), Item("big", **{field: 32768})])
    provider = OpenAICompatibleProvider("https://x.example/v1", "key", client=Client(models))

    assert provider.context_window("big") == 32768
    assert provider.context_window("small") is None
    assert models.calls == 1, "looked up once, then remembered"


def test_an_unreachable_models_list_is_not_an_error_and_not_retried():
    models = Models(error=RuntimeError("down"))
    provider = OpenAICompatibleProvider("https://x.example/v1", "key", client=Client(models))

    assert provider.context_window("any") is None
    assert provider.context_window("any") is None
    assert models.calls == 1


def test_the_reported_window_wins_over_config(app, fake_provider):
    class Reporting(fake_provider):
        def context_window(self, model):
            return 131072

    app.provider = Reporting([])
    app.config.context_window_tokens = 16000

    assert app.context_window() == (131072, True)


def test_config_is_the_fallback_when_the_endpoint_is_silent(app, fake_provider):
    app.provider = fake_provider([])
    app.config.context_window_tokens = 16000

    assert app.context_window() == (16000, False)


def test_context_counts_the_system_prompt_and_tools_before_any_message(app):
    parts = app.context_breakdown()

    assert parts["conversation"] == 0
    assert parts["system"] > 100
    assert parts["tools"] > 100
    assert parts["total"] == parts["system"] + parts["tools"]


def test_context_matches_the_request_that_is_sent(app, fake_provider, delta):
    app.provider = fake_provider([[delta(content="ok")]])
    app.session_manager.add_message("user", "earlier question " * 50)
    app.session_manager.add_message("assistant", "earlier answer " * 50)
    expected = app.context_breakdown()["total"]

    app.send_message("hi")

    sent = app.provider.calls[0]
    actual = estimate_request_tokens(sent["messages"][:-1], sent["tools"])
    assert abs(actual - expected) <= 3


def test_auto_compaction_uses_the_reported_window(app, fake_provider):
    class Reporting(fake_provider):
        def context_window(self, model):
            return 4096

    app.provider = Reporting([])
    app.config.context_window_tokens = 1_000_000
    app.session_manager.add_message("user", "x" * 12000)
    app.session_manager.add_message("assistant", "y" * 12000)

    assert app.should_auto_compact(10)


def test_context_bar_shows_used_and_window(app, fake_provider):
    class Reporting(fake_provider):
        def context_window(self, model):
            return 32768

    app.provider = Reporting([])
    bar = app.context_bar().plain

    assert bar.startswith("context ")
    assert "/ 32.8k" in bar
    assert "window from config" not in bar


@pytest.mark.parametrize(
    ("count", "label"), [(950, "950"), (12345, "12.3k"), (131072, "131k")]
)
def test_format_tokens(count, label):
    assert app_module.format_tokens(count) == label


# --- streaming ------------------------------------------------------------


def test_stream_tail_keeps_the_newest_lines_that_fit():
    console = Console(file=io.StringIO(), width=40, height=10, force_terminal=True)
    text = Text("\n".join(f"line {n}" for n in range(1, 51)))

    lines = console.render_lines(StreamTail(text), console.options, pad=False)
    plain = ["".join(segment.text for segment in line) for line in lines]

    assert len(lines) <= 9
    assert "line 50" in plain[-1]
    assert not any("line 1 " in row or row.strip() == "line 1" for row in plain)


def test_stream_tail_leaves_a_short_reply_alone():
    console = Console(file=io.StringIO(), width=40, height=10, force_terminal=True)

    lines = console.render_lines(StreamTail(Text("a\nb")), console.options, pad=False)

    assert len(lines) == 2


def test_a_reply_taller_than_the_screen_is_printed_whole(app, fake_provider, delta):
    """The live view only shows the tail; the scrollback must still get all of it."""
    output = io.StringIO()
    app.console = Console(file=output, width=60, height=12, force_terminal=True)
    chunks = [delta(content=f"line {n}\n\n") for n in range(1, 41)]
    app.provider = fake_provider([chunks])

    app.send_message("write a lot")

    printed = output.getvalue()
    assert "line 1" in printed
    assert "line 40" in printed


@pytest.mark.parametrize("width", [60, 80, 120])
def test_context_bar_fits_on_one_line(app, width):
    app.console = Console(file=io.StringIO(), force_terminal=False, width=width)

    bar = app.context_bar()

    assert bar.cell_len <= width


# --- /neurochat -----------------------------------------------------------


def test_neurochat_link_matches_the_format_neurochat_reads():
    link = app_module.neurochat_link(
        "https://occurrence-advantages-venues-appearance.trycloudflare.com/v1",
        "H7XSz3oDGuk21u3xf8pvCwfijCw3Jrxw_R-Nm-fi3Lc",
    )

    assert link == (
        "https://chat.neurogrid.cc/#endpoint=https://occurrence-advantages-venues-appearance"
        ".trycloudflare.com/v1&token=H7XSz3oDGuk21u3xf8pvCwfijCw3Jrxw_R-Nm-fi3Lc"
    )


def test_neurochat_link_escapes_characters_that_would_break_it():
    link = app_module.neurochat_link("https://x.example/v1", "a+b&c=d")

    assert link.endswith("#endpoint=https://x.example/v1&token=a%2Bb%26c%3Dd")


def test_neurochat_opens_the_browser_with_the_configured_connection(app, monkeypatch):
    opened = []
    monkeypatch.setattr(app_module, "open_url", lambda url: opened.append(url) or True)
    app.config.base_url = "https://node.trycloudflare.com/v1"
    app.api_key = "secret"

    app.handle_input("/neurochat")

    assert opened == ["https://chat.neurogrid.cc/#endpoint=https://node.trycloudflare.com/v1&token=secret"]


def test_neurochat_needs_a_connection_first(app, monkeypatch):
    opened = []
    monkeypatch.setattr(app_module, "open_url", lambda url: opened.append(url) or True)
    app.config.base_url = ""
    app.api_key = ""

    app.handle_input("/neurochat")

    assert opened == []
    assert "Not connected" in app.console.file.getvalue()


def test_neurochat_shows_the_link_when_no_browser_opens(app, monkeypatch):
    monkeypatch.setattr(app_module, "open_url", lambda url: False)
    app.config.base_url = "https://node.trycloudflare.com/v1"
    app.api_key = "secret"

    app.handle_input("/neurochat")

    printed = app.console.file.getvalue()
    assert "token=secret" in printed
    assert "contains your API key" in printed
