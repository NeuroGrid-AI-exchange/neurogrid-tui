"""What kind of project is this?

Answered from marker files in the workspace root plus a couple of cheap git
commands — never by walking the tree. The result is a handful of lines added
to the system prompt so the agent does not have to spend its first three
tool calls rediscovering that this is, say, a uv-managed Python project with
pytest.

Everything here is best-effort: an unknown project simply yields fewer
facts, never an error.
"""

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

_GIT_TIMEOUT_SECONDS = 5

# marker file -> (language, package manager, test framework, build system)
_MARKERS: list[tuple[str, str, str, str, str]] = [
    ("uv.lock", "Python", "uv", "", ""),
    ("poetry.lock", "Python", "poetry", "", ""),
    ("Pipfile.lock", "Python", "pipenv", "", ""),
    ("requirements.txt", "Python", "pip", "", ""),
    ("pyproject.toml", "Python", "", "", "hatch/setuptools"),
    ("pnpm-lock.yaml", "JavaScript/TypeScript", "pnpm", "", ""),
    ("yarn.lock", "JavaScript/TypeScript", "yarn", "", ""),
    ("bun.lockb", "JavaScript/TypeScript", "bun", "", ""),
    ("package-lock.json", "JavaScript/TypeScript", "npm", "", ""),
    ("package.json", "JavaScript/TypeScript", "", "", ""),
    ("Cargo.toml", "Rust", "cargo", "cargo test", "cargo"),
    ("go.mod", "Go", "go modules", "go test", "go"),
    ("pom.xml", "Java", "maven", "", "maven"),
    ("build.gradle", "Java/Kotlin", "gradle", "", "gradle"),
    ("Gemfile", "Ruby", "bundler", "", ""),
    ("composer.json", "PHP", "composer", "", ""),
    ("CMakeLists.txt", "C/C++", "", "", "cmake"),
    ("Makefile", "", "", "", "make"),
]

# Test frameworks that announce themselves in a config or directory name.
_TEST_MARKERS: list[tuple[str, str]] = [
    ("pytest.ini", "pytest"),
    ("tox.ini", "tox"),
    ("tests", "tests/ directory"),
    ("test", "test/ directory"),
    ("spec", "spec/ directory"),
]


@dataclass
class Workspace:
    """A short, bounded description of the project in the current directory."""

    path: Path
    is_git_repository: bool = False
    branch: str = ""
    languages: list[str] = field(default_factory=list)
    package_managers: list[str] = field(default_factory=list)
    test_frameworks: list[str] = field(default_factory=list)
    build_systems: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """Render the facts worth spending context on."""
        lines = [f"Workspace: {self.path}"]
        if self.is_git_repository:
            branch = f" (branch {self.branch})" if self.branch else ""
            lines.append(f"Git repository: yes{branch}")
        if self.languages:
            lines.append(f"Language: {', '.join(self.languages)}")
        if self.package_managers:
            lines.append(f"Package manager: {', '.join(self.package_managers)}")
        if self.test_frameworks:
            lines.append(f"Tests: {', '.join(self.test_frameworks)}")
        if self.build_systems:
            lines.append(f"Build: {', '.join(self.build_systems)}")
        return "\n".join(lines)


def _unique(values: list[str]) -> list[str]:
    """Preserve detection order while dropping blanks and repeats."""
    seen: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return seen


def _git_branch(path: Path) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, ""
    if result.returncode != 0:
        return False, ""
    return True, result.stdout.strip()


def discover(path: Path) -> Workspace:
    """Describe the workspace from its root markers. Never walks the tree."""
    workspace = Workspace(path=path)
    workspace.is_git_repository, workspace.branch = _git_branch(path)

    languages: list[str] = []
    managers: list[str] = []
    tests: list[str] = []
    builds: list[str] = []

    for marker, language, manager, test, build in _MARKERS:
        if (path / marker).exists():
            languages.append(language)
            managers.append(manager)
            tests.append(test)
            builds.append(build)

    for marker, framework in _TEST_MARKERS:
        if (path / marker).exists():
            tests.append(framework)

    workspace.languages = _unique(languages)
    workspace.package_managers = _unique(managers)
    workspace.test_frameworks = _unique(tests)
    workspace.build_systems = _unique(builds)
    return workspace
