"""Per-test coverage map: which tests execute which line of which file.

Built from one baseline pytest run with pytest-cov dynamic contexts. Lets the
mutation verifier run only the tests that actually execute a mutated line,
instead of the whole suite per mutant. Falls back to None (→ full-suite mode)
when pytest-cov/coverage are not importable in the target environment."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

COV_EXTRA = ["--cov=.", "--cov-context=test", "--cov-report="]

# Python 3.12+'s sys.monitoring coverage core disables line events after first
# hit, silently attributing each line to only the FIRST test that ran it —
# which breaks per-test maps. The C tracer records every (context, line) pair.
COV_ENV = {"COVERAGE_CORE": "ctrace"}

# file path (repo-relative) → line number → set of pytest node ids
CoverageMap = dict[str, dict[int, set[str]]]


def cov_available(python: str) -> bool:
    proc = subprocess.run(
        [python, "-c", "import pytest_cov, coverage"], capture_output=True
    )
    return proc.returncode == 0


def build_map(wt: Path, python: str) -> CoverageMap | None:
    """Parse the .coverage data written by the baseline run into a map.
    Must be called after pytest ran with COV_EXTRA in `wt`."""
    out = wt / "vouch-cov.json"
    proc = subprocess.run(
        [python, "-m", "coverage", "json", "--show-contexts", "-o", str(out)],
        cwd=wt,
        capture_output=True,
    )
    if proc.returncode != 0 or not out.exists():
        return None
    data = json.loads(out.read_text())
    out.unlink(missing_ok=True)
    cmap: CoverageMap = {}
    for path, info in data.get("files", {}).items():
        lines: dict[int, set[str]] = {}
        for line_str, contexts in info.get("contexts", {}).items():
            nodes = {c.split("|", 1)[0] for c in contexts if "::" in c}
            if nodes:
                lines[int(line_str)] = nodes
        cmap[path] = lines
    return cmap


def tests_for_line(cmap: CoverageMap, path: str, line: int) -> set[str]:
    return cmap.get(path, {}).get(line, set())
