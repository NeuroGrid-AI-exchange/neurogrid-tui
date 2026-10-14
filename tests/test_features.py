"""/goal, /graph, attachments, updates, the command catalog, and the browser opener."""

import base64
import io
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest
from rich.console import Console

import nrgrd.app as app_module
import nrgrd.browser as browser
import nrgrd.updates as updates
from nrgrd.attachments import (
    AttachmentError,
    build_user_content,
    load_attachment,
    pasted_paths,
)
from nrgrd.commands import COMMANDS, describe
from nrgrd.context.tokens import IMAGE_TOKENS, estimate_request_tokens
from nrgrd.sessions.graph import ConversationGraph
from tests.helpers import MemoryStore

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


@pytest.fixture
def app(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    monkeypatch.setattr("nrgrd.config.config.user_config_dir", lambda **kw: str(config_dir))
    monkeypatch.setattr("nrgrd.system.prompt.user_config_dir", lambda **kw: str(config_dir))
    monkeypatch.setattr("nrgrd.sessions.store.user_data_dir", lambda **kw: str(data_dir))
    monkeypatch.setattr(app_module, "load_credential_store", MemoryStore)

    instance = app_module.NrgrdApp()
    instance.console = Console(file=io.StringIO(), force_terminal=False, width=120)
    instance.config.model = "test-model"
    instance.working_directory = tmp_path
    return instance


def output(app) -> str:
    return app.console.file.getvalue()


# --- command catalog ------------------------------------------------------


def test_every_command_is_handled(app, monkeypatch):
    """Nothing in the catalog may fall through to the model as a message."""
    sent = []
    monkeypatch.setattr(app, "send_message", lambda *a, **k: sent.append(a))
    for name in (
        "show_help", "show_tools", "show_mcp", "show_mcp_edit_instructions", "compact_conversation",
        "show_connection_information", "show_config", "edit_config", "list_models", "select_model",
        "show_session_information", "show_permissions", "show_diff", "show_context", "open_neurochat",
        "show_sessions", "new_session", "resume_session", "rename_session", "delete_session",
        "clear_session", "show_system_prompt", "edit_system_prompt", "clear_terminal", "print_header",
        "run_goal", "show_attachments", "attach_paths", "attach_clipboard_image", "show_graph", "run_update",
        "show_version",
    ):
        monkeypatch.setattr(app, name, lambda *a, **k: None)
    app.mcp_client.reload = lambda: None

    for command in COMMANDS:
        typed = command.insert + ("x" if command.insert.endswith(" ") else "")
        app.handle_input(typed)

    assert sent == []


def test_describe_picks_the_longest_matching_command():
    assert describe("/mcp reload").usage == "/mcp reload"
    assert describe("/session new work").usage == "/session new <name>"
    assert describe("/goal ship it").usage == "/goal <objective>"
    assert describe("hello") is None


def test_help_lists_the_catalog(app):
    app.show_help()

    for command in COMMANDS:
        assert command.usage in output(app)


# --- browser --------------------------------------------------------------


def test_the_browser_is_detached_from_the_terminal(monkeypatch):
    calls = []
    monkeypatch.setattr(browser.sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(browser.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(browser.subprocess, "Popen", lambda args, **kw: calls.append((args, kw)))

    assert browser.open_url("https://chat.neurogrid.cc/#token=x")

    args, options = calls[0]
    assert args == ["/usr/bin/xdg-open", "https://chat.neurogrid.cc/#token=x"]
    assert options["stdout"] is subprocess.DEVNULL
    assert options["stderr"] is subprocess.DEVNULL
    assert options["stdin"] is subprocess.DEVNULL
    assert options["start_new_session"] is True


def test_no_display_means_no_browser(monkeypatch):
    monkeypatch.setattr(browser.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    assert browser.open_url("https://example.com") is False


def test_neurochat_link_is_clickable_without_printing_the_key(app, monkeypatch):
    monkeypatch.setattr(app_module, "open_url", lambda url: True)
    app.config.base_url = "https://node.trycloudflare.com/v1"
    app.api_key = "secret-key"

    app.open_neurochat()

    assert "secret-key" not in output(app)
    assert "Open NeuroChat" in output(app)


# --- attachments ----------------------------------------------------------


def test_text_and_image_files_load(tmp_path):
    (tmp_path / "notes.md").write_text("# hi\nthere\n", encoding="utf-8")
    (tmp_path / "shot.png").write_bytes(PNG)

    text = load_attachment(tmp_path / "notes.md")
    image = load_attachment(tmp_path / "shot.png")

    assert text.kind == "text" and "there" in text.data
    assert image.kind == "image" and image.mime == "image/png"
    assert base64.b64decode(image.data) == PNG


@pytest.mark.parametrize("make", ["missing", "folder", "binary"])
def test_unattachable_files_say_why(tmp_path, make):
    target = tmp_path / "thing"
    if make == "folder":
        target.mkdir()
    elif make == "binary":
        target.write_bytes(b"\x00\x01\x02 not text")

    with pytest.raises(AttachmentError):
        load_attachment(target)


def test_images_go_as_parts_and_are_noted_in_history(tmp_path):
    (tmp_path / "a.txt").write_text("alpha", encoding="utf-8")
    (tmp_path / "b.png").write_bytes(PNG)
    items = [load_attachment(tmp_path / "a.txt"), load_attachment(tmp_path / "b.png")]

    content, saved = build_user_content("look", items)

    assert content[0]["type"] == "text"
    assert '<file name="a.txt">\nalpha\n</file>' in content[0]["text"]
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "[image attached: b.png]" in saved
    assert "base64" not in saved


def test_image_parts_are_counted_in_the_context(tmp_path):
    (tmp_path / "b.png").write_bytes(PNG)
    content, _ = build_user_content("x", [load_attachment(tmp_path / "b.png")])

    assert estimate_request_tokens([{"role": "user", "content": content}]) >= IMAGE_TOKENS


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX quoting and file:// paths")
def test_a_paste_of_only_paths_is_attached(tmp_path):
    (tmp_path / "my file.png").write_bytes(PNG)
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")

    assert pasted_paths(f"'{tmp_path}/my file.png'", tmp_path) == [tmp_path / "my file.png"]
    assert pasted_paths(f"file://{tmp_path}/my%20file.png", tmp_path) == [tmp_path / "my file.png"]
    assert pasted_paths(f"{tmp_path}/my\\ file.png {tmp_path}/b.txt", tmp_path) == [
        tmp_path / "my file.png",
        tmp_path / "b.txt",
    ]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows drag-and-drop quoting")
def test_a_windows_drop_is_attached(tmp_path):
    (tmp_path / "my file.png").write_bytes(PNG)
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    image, text = tmp_path / "my file.png", tmp_path / "b.txt"

    assert pasted_paths(f'"{image}"', tmp_path) == [image]
    assert pasted_paths(f'"{image}" "{text}"', tmp_path) == [image, text]


def test_a_sentence_mentioning_a_path_is_just_text(tmp_path):
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")

    assert pasted_paths(f"please read {tmp_path}/b.txt", tmp_path) is None
    assert pasted_paths("", tmp_path) is None


def test_attach_then_send(app, fake_provider, delta, tmp_path):
    (tmp_path / "shot.png").write_bytes(PNG)
    app.provider = fake_provider([[delta(content="I see it.")]])

    app.handle_input("/attach shot.png")
    app.send_message("what's this?")

    sent = app.provider.calls[0]["messages"][-1]["content"]
    assert sent[1]["type"] == "image_url"
    assert app.pending_attachments == []
    saved = app.session_manager.get_messages()[0].content
    assert "[image attached: shot.png]" in saved


def test_attachments_survive_a_failed_send(app, fake_provider, tmp_path):
    (tmp_path / "a.txt").write_text("alpha", encoding="utf-8")

    class Failing(fake_provider):
        def stream_chat(self, model, messages, tools=None):
            raise RuntimeError("down")
            yield  # pragma: no cover

    app.provider = Failing([])
    app.handle_input("/attach a.txt")
    app.send_message("read this")

    assert [item.name for item in app.pending_attachments] == ["a.txt"]


# --- conversation graph ---------------------------------------------------


def test_graph_records_turns_tools_and_files(tmp_path):
    graph = ConversationGraph(tmp_path / "g.json")
    first = graph.start_turn("fix the test")
    graph.add_tool(first, "read_file", json.dumps({"path": "src/app.py"}))
    graph.add_tool(first, "edit_file", json.dumps({"path": "src/app.py", "old_text": "a", "new_text": "b"}))
    graph.add_tool(first, "shell", json.dumps({"command": "pytest -q"}), status="denied")
    graph.finish_turn(first, "Fixed.", "finished")
    second = graph.start_turn("now the docs")
    graph.save()

    loaded = ConversationGraph(tmp_path / "g.json")
    assert [turn["id"] for turn in loaded.turns()] == [first, second]
    assert {"from": first, "to": second, "kind": "next"} in loaded.edges
    assert loaded.file_summary() == [("src/app.py", 1, 1)]
    tools = loaded.tools_of(first)
    assert [tool["label"] for tool in tools] == ["read_file", "edit_file", "shell"]
    assert tools[2]["status"] == "denied" and tools[2]["detail"] == "pytest -q"


def test_a_damaged_graph_starts_fresh(tmp_path):
    path = tmp_path / "g.json"
    path.write_text("{not json", encoding="utf-8")

    assert ConversationGraph(path).turns() == []


def test_a_turn_with_tools_lands_in_the_graph(app, fake_provider, delta, tmp_path):
    (tmp_path / "x.py").write_text("print(1)\n", encoding="utf-8")
    app.provider = fake_provider(
        [
            [delta(tool_name="read_file", tool_args='{"path": "x.py"}', tool_id="c1")],
            [delta(content="It prints 1.")],
        ]
    )

    app.send_message("what does x.py do?")
    app.show_graph()

    graph = ConversationGraph(app.session_manager.get_graph_path())
    assert graph.turns()[0]["outcome"] == "finished"
    assert graph.file_summary() == [("x.py", 1, 0)]
    assert "read_file" in output(app) and "x.py" in output(app)


def test_graph_follows_its_session(app):
    store = app.session_manager.store
    path = app.session_manager.get_graph_path()
    graph = ConversationGraph(path)
    graph.start_turn("hello")
    graph.save()
    app.session_manager.add_message("user", "hello")

    store.rename("renamed")
    assert not path.exists() and store.graph_path.exists()
    assert app.session_manager.list_sessions()[0].name == "renamed", "graphs aren't listed as sessions"

    store.clear()
    assert not store.graph_path.exists()


# --- /goal ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("reply", "verdict"),
    [
        ("All done.\n\nGOAL ACHIEVED", ("done", "")),
        ("Done.\n**GOAL ACHIEVED**\n", ("done", "")),
        ("Stuck.\nGOAL BLOCKED: need the API key", ("blocked", "need the API key")),
        ("Made progress on step 1.", ("continue", "")),
        ("", ("continue", "")),
    ],
)
def test_goal_verdict(reply, verdict):
    assert app_module.goal_verdict(reply) == verdict


def test_goal_keeps_going_until_achieved(app, fake_provider, delta):
    app.provider = fake_provider(
        [
            [delta(content="Step one done.")],
            [delta(content="Step two done.")],
            [delta(content="Verified.\n\nGOAL ACHIEVED")],
        ]
    )

    app.handle_input("/goal make the tests pass")

    assert len(app.provider.calls) == 3
    assert "make the tests pass" in app.provider.calls[0]["messages"][-1]["content"]
    assert "Continue working toward the goal" in app.provider.calls[1]["messages"][-1]["content"]
    assert "Goal achieved" in output(app)


def test_goal_stops_when_blocked(app, fake_provider, delta):
    app.provider = fake_provider([[delta(content="GOAL BLOCKED: which database?")]])

    app.run_goal("migrate the db")

    assert len(app.provider.calls) == 1
    assert "which database?" in output(app)


def test_goal_stops_when_interrupted(app, fake_provider, delta):
    class Interrupted(fake_provider):
        def stream_chat(self, model, messages, tools=None):
            self.calls.append(messages)
            yield delta(content="partial")
            raise KeyboardInterrupt

    app.provider = Interrupted([])
    app.run_goal("anything")

    assert len(app.provider.calls) == 1
    assert "Goal stopped" in output(app)


def test_the_agent_has_no_iteration_limit(fake_provider, delta):
    """A turn keeps going as long as the model keeps calling tools."""
    from nrgrd.agent import Agent, AgentFinished
    from nrgrd.tools.registry import PermissionLevel, Tool, ToolRegistry

    registry = ToolRegistry()
    registry.register(Tool("ping", "ping", {"type": "object", "properties": {}}, PermissionLevel.ALLOW, lambda a: "pong"))
    rounds = [[delta(tool_name="ping", tool_args="{}", tool_id=f"c{n}")] for n in range(40)]
    provider = fake_provider([*rounds, [delta(content="done")]])

    events = list(Agent(provider, "m", registry).run([{"role": "user", "content": "go"}]))

    assert isinstance(events[-1], AgentFinished)
    assert len(provider.calls) == 41


def test_goal_has_no_round_limit(app, fake_provider, delta):
    app.provider = fake_provider(
        [[delta(content=f"step {n}")] for n in range(30)] + [[delta(content="GOAL ACHIEVED")]]
    )

    app.run_goal("long job")

    assert len(app.provider.calls) == 31
    assert "Goal achieved" in output(app)


# --- graph drawing --------------------------------------------------------


def drawn(graph, width=100) -> str:
    from nrgrd.widgets.graph_view import render_graph

    return render_graph(graph, width).plain


def build(tmp_path, turns):
    graph = ConversationGraph(tmp_path / "g.json")
    for label, tools in turns:
        turn = graph.start_turn(label)
        for name, path in tools:
            graph.add_tool(turn, name, json.dumps({"path": path} if path else {}))
        graph.finish_turn(turn, "ok", "finished")
    return graph


def test_a_file_shared_by_turns_is_one_lane(tmp_path):
    graph = build(
        tmp_path,
        [
            ("first", [("read_file", "src/app.py"), ("edit_file", "README.md")]),
            ("second", [("edit_file", "src/app.py")]),
        ],
    )

    picture = drawn(graph)
    lines = picture.splitlines()

    assert sum("src/app.py" in line for line in lines) == 1, "one node per file"
    first = next(line for line in lines if "first" in line)
    second = next(line for line in lines if "second" in line)
    assert "○" in first and "●" in first  # read app.py, wrote README.md
    assert "●" in second
    assert "✎1 ○1" in next(line for line in lines if "src/app.py" in line)


def test_a_turn_passing_an_open_lane_crosses_it(tmp_path):
    graph = build(
        tmp_path,
        [
            ("opens a", [("read_file", "a.py")]),
            ("only b", [("read_file", "b.py")]),
        ],
    )

    second = next(line for line in drawn(graph).splitlines() if "only b" in line)

    assert "┼" in second


def test_a_narrow_terminal_drops_the_quietest_files(tmp_path):
    graph = build(tmp_path, [(f"turn {n}", [("read_file", f"file{n}.py")]) for n in range(12)])

    picture = drawn(graph, width=60)

    assert "not drawn (too narrow)" in picture
    assert all(len(line) <= 60 for line in picture.splitlines())


def test_a_session_without_files_still_draws_its_turns(tmp_path):
    graph = build(tmp_path, [("hello", []), ("run it", [("git_status", None)])])

    picture = drawn(graph)

    assert "hello" in picture and "run it" in picture and "git_status" in picture


# --- updates --------------------------------------------------------------


@pytest.mark.parametrize(
    ("candidate", "current", "newer"),
    [
        ("0.2.0", "0.1.0", True),
        ("0.1.1", "0.1.0", True),
        ("0.1.0", "0.1.0", False),
        ("0.1.0", "0.2.0", False),
        ("0.2", "0.2.0", False),
        ("0.2.0", "0.2.0.dev3+gabc123", True),
        ("0.1.0", "0.2.0.dev3+gabc123", False),
        ("1.0.0", "0.9.9", True),
        ("garbage", "0.1.0", False),
    ],
)
def test_is_newer(candidate, current, newer):
    assert updates.is_newer(candidate, current) is newer


def test_the_pypi_answer_is_cached_for_a_day(tmp_path, monkeypatch):
    fetches = []
    monkeypatch.setattr(updates, "fetch_latest_version", lambda: fetches.append(1) or "9.9.9")
    cache = tmp_path / "update-check.json"
    now = datetime(2026, 1, 1, tzinfo=UTC)

    assert updates.cached_latest_version(cache, now) == "9.9.9"
    assert updates.cached_latest_version(cache, now + timedelta(hours=5)) == "9.9.9"
    assert len(fetches) == 1
    updates.cached_latest_version(cache, now + timedelta(days=2))
    assert len(fetches) == 2


@pytest.mark.parametrize(
    ("prefix", "command"),
    [
        ("/home/me/.local/share/uv/tools/nrgrd", ["uv", "tool", "upgrade", "nrgrd"]),
        ("C:\\Users\\me\\AppData\\Roaming\\uv\\data\\tools\\nrgrd", ["uv", "tool", "upgrade", "nrgrd"]),
        ("/home/me/.local/share/pipx/venvs/nrgrd", ["pipx", "upgrade", "nrgrd"]),
    ],
)
def test_upgrade_command_follows_the_installer(prefix, command):
    assert updates.upgrade_command(prefix, from_source=False) == command


def test_pip_installs_upgrade_with_pip():
    command = updates.upgrade_command("/usr", from_source=False)
    assert command[1:] == ["-m", "pip", "install", "--upgrade", "nrgrd"]


def test_a_source_checkout_is_told_to_git_pull(app, monkeypatch):
    monkeypatch.setattr(app_module, "fetch_latest_version", lambda: "99.0.0")
    monkeypatch.setattr(app_module, "upgrade_command", lambda: None)

    app.run_update()

    assert "git pull" in output(app)


def test_up_to_date_says_so(app, monkeypatch):
    monkeypatch.setattr(app_module, "fetch_latest_version", lambda: "0.0.1")

    app.run_update()

    assert "latest nrgrd" in output(app)


def test_the_startup_notice_shows_once(app):
    app.update_available = "99.0.0"

    app.show_update_notice()
    app.show_update_notice()

    assert output(app).count("99.0.0 is available") == 1


def test_the_check_can_be_turned_off(monkeypatch):
    monkeypatch.setenv(updates.DISABLE_ENV, "1")
    assert updates.update_check_disabled()


# --- version --------------------------------------------------------------


def test_version_command(app, monkeypatch):
    monkeypatch.setattr(app_module, "upgrade_command", lambda: ["uv", "tool", "upgrade", "nrgrd"])

    app.handle_input("/version")

    text = output(app)
    assert f"nrgrd {app_module.__version__}" in text
    assert "installed with uv" in text
    assert "Python " in text


def test_version_mentions_an_available_update(app, monkeypatch):
    monkeypatch.setattr(app_module, "upgrade_command", lambda: None)
    app.update_available = "99.0.0"

    app.handle_input("/version")

    assert "installed from source" in output(app)
    assert "99.0.0 is available" in output(app)


def test_the_logo_screen_shows_the_version(app):
    app.print_logo()

    assert f"v{app_module.__version__}" in output(app)
