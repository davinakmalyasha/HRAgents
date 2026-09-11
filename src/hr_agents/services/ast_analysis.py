"""Static analysis for repositories: complexity metrics and framework detection.

Runs entirely in-process on a local checkout (no shell, no network). Python uses
``radon``; other languages use ``lizard``. Bounded by file count and size so a
hostile repository cannot exhaust the worker.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from radon.complexity import cc_visit

MAX_FILES = 300
MAX_FILE_BYTES = 512_000
MAX_DEPTH = 8

_PY_SUFFIXES = {".py"}
_LIZARD_SUFFIXES = {
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".java",
    ".kt",
    ".cs",
    ".rb",
    ".go",
    ".rs",
    ".c",
    ".cpp",
    ".h",
    ".php",
    ".swift",
    ".scala",
    ".m",
    ".mm",
}

_FRAMEWORK_SOURCES: tuple[str, ...] = (
    "requirements.txt",
    "pyproject.toml",
    "package.json",
    "go.mod",
    "Gemfile",
    "pom.xml",
    "build.gradle",
)

_TEST_DIR_NAMES = {"tests", "test", "__tests__", "spec", "specs"}
_CI_PATHS = (
    ".github/workflows",
    ".gitlab-ci.yml",
    ".circleci/config.yml",
    "Jenkinsfile",
)


class AnalysisError(ValueError):
    """Raised when analysis input is invalid (missing path, not a directory)."""


class UnsafePathError(AnalysisError):
    """Raised when the requested path escapes the allowed root."""


@dataclass
class ComplexityReport:
    functions_analyzed: int = 0
    avg_complexity: float | None = None
    max_complexity: float | None = None
    files_analyzed: int = 0
    files_skipped: int = 0
    avg_function_length: float | None = None


@dataclass
class RepoAnalysis:
    complexity: ComplexityReport = field(default_factory=ComplexityReport)
    frameworks: list[str] = field(default_factory=list)
    has_tests: bool = False
    has_ci: bool = False
    has_readme: bool = False
    languages: dict[str, int] = field(default_factory=dict)


def resolve_repo_path(repo_path: str | Path, *, root: Path) -> Path:
    """Resolve a repository path and enforce it stays inside ``root``."""
    candidate = (
        (root / repo_path).resolve()
        if not Path(repo_path).is_absolute()
        else Path(repo_path).resolve()
    )
    root_resolved = root.resolve()
    if root_resolved != candidate and root_resolved not in candidate.parents:
        raise UnsafePathError(f"path {repo_path!r} escapes the allowed analysis root")
    if not candidate.is_dir():
        raise AnalysisError(f"not a directory: {repo_path!r}")
    return candidate


def _iter_files(repo: Path, suffixes: set[str]) -> list[Path]:
    files: list[Path] = []
    for path in sorted(repo.rglob("*")):
        if len(files) >= MAX_FILES:
            break
        try:
            relative = path.relative_to(repo)
        except ValueError:
            continue
        if len(relative.parts) > MAX_DEPTH:
            continue
        if any(part.startswith(".") and part not in {".github"} for part in relative.parts):
            continue
        if path.is_file() and path.suffix.lower() in suffixes:
            files.append(path)
    return files


def analyze_python(repo: Path) -> ComplexityReport:
    """Cyclomatic complexity for Python sources via radon."""
    report = ComplexityReport()
    total_complexity = 0.0
    total_length = 0.0
    function_count = 0
    max_complexity: float | None = None

    for path in _iter_files(repo, _PY_SUFFIXES):
        if path.stat().st_size > MAX_FILE_BYTES:
            report.files_skipped += 1
            continue
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            blocks = cc_visit(source)
        except Exception:
            report.files_skipped += 1
            continue

        report.files_analyzed += 1
        for block in blocks:
            complexity = float(getattr(block, "complexity", 1.0))
            total_complexity += complexity
            total_length += float(getattr(block, "endline", 0) - getattr(block, "lineno", 0) + 1)
            function_count += 1
            max_complexity = (
                complexity if max_complexity is None else max(max_complexity, complexity)
            )

    report.functions_analyzed = function_count
    if function_count:
        report.avg_complexity = round(total_complexity / function_count, 4)
        report.avg_function_length = round(total_length / function_count, 2)
    report.max_complexity = max_complexity
    return report


def analyze_other_languages(repo: Path) -> ComplexityReport:
    """Cyclomatic complexity for non-Python sources via lizard (optional)."""
    try:
        import lizard
    except ImportError:  # pragma: no cover — lizard is a project dependency
        return ComplexityReport()

    report = ComplexityReport()
    complexities: list[float] = []

    for path in _iter_files(repo, _LIZARD_SUFFIXES):
        if path.stat().st_size > MAX_FILE_BYTES:
            report.files_skipped += 1
            continue
        try:
            analysis = lizard.analyze_file(str(path))
        except Exception:
            report.files_skipped += 1
            continue
        report.files_analyzed += 1
        complexities.extend(
            float(function.cyclomatic_complexity) for function in analysis.function_list
        )

    report.functions_analyzed = len(complexities)
    if complexities:
        report.avg_complexity = round(sum(complexities) / len(complexities), 4)
        report.max_complexity = max(complexities)
    return report


def merge_complexity(*reports: ComplexityReport) -> ComplexityReport:
    functions = sum(r.functions_analyzed for r in reports)
    if functions == 0:
        return ComplexityReport(
            files_analyzed=sum(r.files_analyzed for r in reports),
            files_skipped=sum(r.files_skipped for r in reports),
        )

    weighted_sum = sum((r.avg_complexity or 0.0) * r.functions_analyzed for r in reports)
    maxima = [r.max_complexity for r in reports if r.max_complexity is not None]
    lengths = [
        (r.avg_function_length or 0.0, r.functions_analyzed)
        for r in reports
        if r.avg_function_length is not None
    ]
    return ComplexityReport(
        functions_analyzed=functions,
        avg_complexity=round(weighted_sum / functions, 4),
        max_complexity=max(maxima) if maxima else None,
        files_analyzed=sum(r.files_analyzed for r in reports),
        files_skipped=sum(r.files_skipped for r in reports),
        avg_function_length=(
            round(sum(avg * count for avg, count in lengths) / functions, 2) if lengths else None
        ),
    )


def _frameworks_from_requirements(text: str) -> list[str]:
    frameworks: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-", "git+", "http")):
            continue
        name = re.split(r"[<>=!\[;,\s]", line, maxsplit=1)[0].strip()
        if name:
            frameworks.append(name.lower())
    return frameworks


def _frameworks_from_pyproject(text: str) -> list[str]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return []

    names: list[str] = []
    project = data.get("project", {})
    for dep in project.get("dependencies", []):
        name = re.split(r"[<>=!\[;,\s]", dep, maxsplit=1)[0].strip()
        if name:
            names.append(name.lower())
    poetry = data.get("tool", {}).get("poetry", {})
    for section in ("dependencies", "dev-dependencies"):
        for name in poetry.get(section) or {}:
            if name.lower() != "python":
                names.append(name.lower())
    return names


def _frameworks_from_package_json(text: str) -> list[str]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    names = list((data.get("dependencies") or {}).keys())
    names.extend((data.get("devDependencies") or {}).keys())
    return [name.lower() for name in names if name]


def _frameworks_from_gomod(text: str) -> list[str]:
    names: list[str] = []
    for match in re.finditer(r"^\s*([\w.\-]+/[\w.\-/]+)\s+v", text, re.MULTILINE):
        names.append(match.group(1).lower())
    return names


def detect_frameworks(repo: Path) -> list[str]:
    """Detect dependencies from manifest files (deterministic, sorted, unique)."""
    found: set[str] = set()

    for name in _FRAMEWORK_SOURCES:
        manifest = repo / name
        if not manifest.is_file() or manifest.stat().st_size > MAX_FILE_BYTES:
            continue
        text = manifest.read_text(encoding="utf-8", errors="replace")
        if name == "requirements.txt":
            found.update(_frameworks_from_requirements(text))
        elif name == "pyproject.toml":
            found.update(_frameworks_from_pyproject(text))
        elif name == "package.json":
            found.update(_frameworks_from_package_json(text))
        elif name == "go.mod":
            found.update(_frameworks_from_gomod(text))

    return sorted(found)


def _has_tests(repo: Path) -> bool:
    if any((repo / name).is_dir() for name in _TEST_DIR_NAMES):
        return True
    return any(
        path.name.startswith("test_") or path.name.endswith("_test.py")
        for path in _iter_files(repo, _PY_SUFFIXES)
    )


def _has_ci(repo: Path) -> bool:
    return any((repo / value).exists() for value in _CI_PATHS)


def analyze_repository(repo: Path, *, max_commits: int = 0) -> RepoAnalysis:
    """Full static analysis of a repository checkout."""
    del max_commits  # reserved for future git-history analysis
    if not repo.is_dir():
        raise AnalysisError(f"not a directory: {repo}")

    complexity = merge_complexity(analyze_python(repo), analyze_other_languages(repo))
    languages: dict[str, int] = {}
    for path in _iter_files(repo, _PY_SUFFIXES | _LIZARD_SUFFIXES):
        languages[path.suffix.lower()] = languages.get(path.suffix.lower(), 0) + 1

    return RepoAnalysis(
        complexity=complexity,
        frameworks=detect_frameworks(repo),
        has_tests=_has_tests(repo),
        has_ci=_has_ci(repo),
        has_readme=(repo / "README.md").is_file() or (repo / "README.rst").is_file(),
        languages=languages,
    )
