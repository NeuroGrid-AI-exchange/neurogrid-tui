"""The context window must survive a large repository."""

from pathlib import Path

from nrgrd.tools.registry import PermissionLevel, Tool, ToolRegistry
from nrgrd.workspace.tools import MAX_READ_LINES, WorkspaceTools


def noisy_tool(output: str) -> Tool:
    return Tool(
        "noisy",
        "prints a lot",
        {"type": "object", "properties": {}},
        PermissionLevel.ALLOW,
        lambda arguments: output,
    )


def test_a_huge_tool_result_is_capped():
    registry = ToolRegistry(max_result_chars=100)
    registry.register(noisy_tool("x" * 5000))

    result = registry.execute("noisy", "{}")

    assert len(result) < 500
    assert "truncated" in result


def test_a_small_result_is_untouched():
    registry = ToolRegistry(max_result_chars=100)
    registry.register(noisy_tool("just a little"))

    assert registry.execute("noisy", "{}") == "just a little"


def test_read_file_is_line_numbered(tmp_path: Path):
    target = tmp_path / "sample.py"
    target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    result = WorkspaceTools(tmp_path).read_file("sample.py")

    assert "1  alpha" in result
    assert "3  gamma" in result


def test_read_file_slices_a_large_file_instead_of_dumping_it(tmp_path: Path):
    target = tmp_path / "big.py"
    target.write_text("\n".join(f"line {n}" for n in range(5000)), encoding="utf-8")

    result = WorkspaceTools(tmp_path).read_file("big.py")

    assert result.count("\n") <= MAX_READ_LINES + 5
    assert "more lines" in result
    assert "offset=" in result, "the agent needs to know how to continue"


def test_read_file_honours_offset_and_limit(tmp_path: Path):
    target = tmp_path / "sample.txt"
    target.write_text("\n".join(f"line {n}" for n in range(1, 21)), encoding="utf-8")

    result = WorkspaceTools(tmp_path).read_file("sample.txt", offset=5, limit=2)

    assert "5  line 5" in result
    assert "6  line 6" in result
    assert "line 7" not in result


def test_read_file_reports_binary_rather_than_garbage(tmp_path: Path):
    target = tmp_path / "blob.bin"
    target.write_bytes(b"\x00\x01\x02\xff\xfe garbage")

    result = WorkspaceTools(tmp_path).read_file("blob.bin")

    assert "binary" in result.lower()


def test_reads_cannot_escape_the_workspace(tmp_path: Path):
    """Traversal is refused on the path the agent actually calls."""
    (tmp_path / "inside").mkdir()
    tools = WorkspaceTools(tmp_path / "inside")

    result = tools.execute("read_file", '{"path": "../../etc/passwd"}')

    assert "workspace" in result.lower()
    assert "root:" not in result
