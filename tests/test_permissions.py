from nrgrd.agent.permissions import PermissionManager
from nrgrd.tools.registry import PermissionLevel


def test_allow_never_calls_the_callback():
    calls = []
    manager = PermissionManager(callback=lambda name, args: calls.append(name) or "no")

    assert manager.check("read_file", "{}", PermissionLevel.ALLOW) is True
    assert calls == []


def test_deny_never_calls_the_callback():
    calls = []
    manager = PermissionManager(callback=lambda name, args: calls.append(name) or "yes")

    assert manager.check("dangerous", "{}", PermissionLevel.DENY) is False
    assert calls == []


def test_ask_without_callback_denies_by_default():
    manager = PermissionManager()
    assert manager.check("shell", "{}", PermissionLevel.ASK) is False


def test_ask_defers_to_callback():
    manager = PermissionManager(callback=lambda name, args: "yes")
    assert manager.check("shell", "{}", PermissionLevel.ASK) is True


def test_ask_denied_by_callback():
    manager = PermissionManager(callback=lambda name, args: "no")
    assert manager.check("shell", "{}", PermissionLevel.ASK) is False


def test_always_is_remembered_for_the_session():
    calls = []
    manager = PermissionManager(callback=lambda name, args: calls.append(1) or "always")

    assert manager.check("shell", "{}", PermissionLevel.ASK) is True
    assert manager.check("shell", "{}", PermissionLevel.ASK) is True
    assert len(calls) == 1, "the callback should only fire once after 'always'"
