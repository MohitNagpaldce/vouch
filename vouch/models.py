from __future__ import annotations

import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Severity(str, Enum):
    INFO = "info"
    WARN = "warn"
    BLOCK = "block"


class Verdict(str, Enum):
    PASS = "pass"
    WARN = "warn"
    BLOCK = "block"
    SKIP = "skip"
    ERROR = "error"


@dataclass
class Finding:
    verifier: str
    severity: Severity
    message: str
    file: str | None = None
    line: int | None = None
    data: dict = field(default_factory=dict)


@dataclass
class VerifierResult:
    verifier: str
    verdict: Verdict
    findings: list[Finding] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    duration_s: float = 0.0
    note: str = ""


@dataclass
class FileDiff:
    path: str
    changed_lines: set[int] = field(default_factory=set)
    added_text: list[tuple[int, str]] = field(default_factory=list)
    is_new: bool = False

    @property
    def is_test(self) -> bool:
        p = Path(self.path)
        name = p.name
        return (
            name.startswith("test_")
            or name.endswith("_test.py")
            or "tests" in p.parts
            or "test" in p.parts
        )

    @property
    def is_python(self) -> bool:
        return self.path.endswith(".py")


@dataclass
class DiffContext:
    base_ref: str
    head_ref: str
    merge_base: str
    files: list[FileDiff] = field(default_factory=list)
    raw: str = ""

    @property
    def python_impl_files(self) -> list[FileDiff]:
        return [f for f in self.files if f.is_python and not f.is_test]

    @property
    def python_test_files(self) -> list[FileDiff]:
        return [f for f in self.files if f.is_python and f.is_test]


@dataclass
class Provenance:
    is_ai: bool = False
    models: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)


@dataclass
class RunContext:
    repo: Path
    diff: DiffContext
    provenance: Provenance
    tier_name: str
    tier_config: dict
    python: str = sys.executable
    config: dict = field(default_factory=dict)
    # Run test-touching verifiers directly in `repo` instead of a disposable
    # worktree. Only safe when `repo` is itself throwaway (e.g. a harness
    # worktree); needed when the target package is pip-installed -e from
    # `repo`, so mutated files are actually the ones imported.
    in_place: bool = False
