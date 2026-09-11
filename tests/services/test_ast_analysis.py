from pathlib import Path

import pytest

from hr_agents.services.ast_analysis import (
    AnalysisError,
    UnsafePathError,
    analyze_repository,
    detect_frameworks,
    resolve_repo_path,
)

PY_GOOD = '''
"""Module with simple functions."""


def add(a: int, b: int) -> int:
    return a + b


def classify(value: int) -> str:
    if value < 0:
        return "negative"
    if value == 0:
        return "zero"
    if value < 10:
        return "small"
    return "large"
'''

PY_COMPLEX = """
def messy(value, flag):
    total = 0
    for index in range(value):
        if index % 2 == 0 and flag:
            total += index
        elif index % 3 == 0 or flag:
            total -= index
        else:
            total += 1
    return total
"""


def build_repo(root: Path) -> Path:
    repo = root / "sample-repo"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / "src" / "core.py").write_text(PY_GOOD, encoding="utf-8")
    (repo / "src" / "messy.py").write_text(PY_COMPLEX, encoding="utf-8")
    (repo / "tests" / "test_core.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    (repo / ".github" / "workflows" / "ci.yml").write_text("name: CI\n", encoding="utf-8")
    (repo / "README.md").write_text("# Sample\n", encoding="utf-8")
    (repo / "requirements.txt").write_text(
        "fastapi>=0.115\n# comment\npydantic==2.13.5\nuvicorn[standard]\n", encoding="utf-8"
    )
    (repo / "package.json").write_text(
        '{"dependencies": {"react": "^19.0.0"}, "devDependencies": {"vite": "^6.0.0"}}',
        encoding="utf-8",
    )
    (repo / "go.mod").write_text(
        "module example.com/svc\n\nrequire (\n\tgithub.com/gin-gonic/gin v1.10.0\n)\n",
        encoding="utf-8",
    )
    return repo


def test_resolve_repo_path_enforces_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    inside = root / "repo"
    inside.mkdir()

    assert resolve_repo_path("repo", root=root) == inside.resolve()

    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(UnsafePathError, match="escapes"):
        resolve_repo_path(str(outside), root=root)


def test_resolve_repo_path_missing_directory(tmp_path: Path) -> None:
    root = tmp_path
    with pytest.raises(AnalysisError, match="not a directory"):
        resolve_repo_path("missing", root=root)


def test_analyze_repository_full(tmp_path: Path) -> None:
    repo = build_repo(tmp_path)
    analysis = analyze_repository(repo)

    assert analysis.complexity.files_analyzed >= 2
    assert analysis.complexity.functions_analyzed >= 3
    assert analysis.complexity.avg_complexity is not None
    assert analysis.complexity.max_complexity is not None
    assert analysis.complexity.max_complexity >= 3  # branchy function
    assert analysis.has_tests
    assert analysis.has_ci
    assert analysis.has_readme
    assert analysis.languages.get(".py") == 3


def test_detect_frameworks_multiple_manifests(tmp_path: Path) -> None:
    repo = build_repo(tmp_path)
    frameworks = detect_frameworks(repo)

    assert "fastapi" in frameworks
    assert "pydantic" in frameworks
    assert "uvicorn" in frameworks
    assert "react" in frameworks
    assert "vite" in frameworks
    assert "github.com/gin-gonic/gin" in frameworks
    assert frameworks == sorted(frameworks)


def test_framework_detection_tolerates_broken_manifests(tmp_path: Path) -> None:
    repo = tmp_path / "broken"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("not [valid toml", encoding="utf-8")
    (repo / "package.json").write_text("{not json", encoding="utf-8")

    assert detect_frameworks(repo) == []


def test_analysis_skips_unparseable_python(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "broken.py").write_text("def oops(:\n", encoding="utf-8")
    (repo / "fine.py").write_text("def ok():\n    return 1\n", encoding="utf-8")

    analysis = analyze_repository(repo)
    assert analysis.complexity.files_analyzed == 1
    assert analysis.complexity.files_skipped == 1


def test_analysis_ignores_hidden_directories(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "visible.py").write_text("def ok():\n    return 1\n", encoding="utf-8")
    hidden = repo / ".venv"
    hidden.mkdir()
    (hidden / "vendored.py").write_text("def big():\n" + "    pass\n" * 100, encoding="utf-8")

    analysis = analyze_repository(repo)
    assert analysis.complexity.files_analyzed == 1


def test_analyze_non_directory_raises(tmp_path: Path) -> None:
    file_path = tmp_path / "file.txt"
    file_path.write_text("x", encoding="utf-8")
    with pytest.raises(AnalysisError):
        analyze_repository(file_path)
