from pathlib import Path

from nrgrd.workspace import discover


def test_detects_a_uv_python_project_with_tests(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()

    workspace = discover(tmp_path)

    assert "Python" in workspace.languages
    assert "uv" in workspace.package_managers
    assert "tests/ directory" in workspace.test_frameworks


def test_detects_a_rust_project(tmp_path: Path):
    (tmp_path / "Cargo.toml").write_text("[package]\n", encoding="utf-8")

    workspace = discover(tmp_path)

    assert workspace.languages == ["Rust"]
    assert workspace.package_managers == ["cargo"]
    assert "cargo test" in workspace.test_frameworks


def test_detects_a_node_project_and_its_lockfile(tmp_path: Path):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")

    workspace = discover(tmp_path)

    assert workspace.languages == ["JavaScript/TypeScript"]
    assert workspace.package_managers == ["pnpm"]


def test_an_unknown_directory_yields_facts_not_errors(tmp_path: Path):
    workspace = discover(tmp_path)

    assert workspace.languages == []
    assert workspace.summary().startswith("Workspace:")


def test_summary_only_reports_what_was_found(tmp_path: Path):
    (tmp_path / "go.mod").write_text("module x\n", encoding="utf-8")

    summary = discover(tmp_path).summary()

    assert "Language: Go" in summary
    assert "Build:" not in summary or "go" in summary
    # Nothing should claim a package manager that was not detected.
    assert "npm" not in summary


def test_discovery_does_not_walk_the_tree(tmp_path: Path):
    """Markers are read from the root only, so a huge repo stays cheap."""
    buried = tmp_path / "vendor" / "nested" / "deep"
    buried.mkdir(parents=True)
    (buried / "Cargo.toml").write_text("[package]\n", encoding="utf-8")

    workspace = discover(tmp_path)

    assert workspace.languages == []
