from __future__ import annotations

import difflib
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

from ..models import Finding, RunContext, Severity, Verdict, VerifierResult
from .base import Verifier, register

_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+([A-Za-z_][A-Za-z0-9_]*)")

# import name → PyPI distribution name, for common mismatches
_IMPORT_TO_DIST = {
    "yaml": "PyYAML",
    "PIL": "Pillow",
    "sklearn": "scikit-learn",
    "cv2": "opencv-python",
    "bs4": "beautifulsoup4",
    "dotenv": "python-dotenv",
    "dateutil": "python-dateutil",
    "jwt": "PyJWT",
    "attr": "attrs",
    "OpenSSL": "pyOpenSSL",
}

_POPULAR = [
    "requests", "numpy", "pandas", "flask", "django", "pytest", "click",
    "pydantic", "sqlalchemy", "boto3", "httpx", "rich", "typer", "fastapi",
    "cryptography", "pillow", "scipy", "matplotlib", "beautifulsoup4",
    "python-dateutil", "python-dotenv", "pyyaml", "pyjwt", "urllib3",
]

_NEW_PACKAGE_DAYS = 90


def _fetch_pypi(dist: str, timeout: float = 10.0) -> dict | None:
    """Return PyPI metadata, {} if the package does not exist, None if offline."""
    url = f"https://pypi.org/pypi/{dist}/json"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}
        return None
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def _latest_upload(meta: dict) -> datetime | None:
    times = [
        datetime.fromisoformat(f["upload_time_iso_8601"].replace("Z", "+00:00"))
        for files in meta.get("releases", {}).values()
        for f in files
        if "upload_time_iso_8601" in f
    ]
    return max(times) if times else None


def _first_upload(meta: dict) -> datetime | None:
    times = [
        datetime.fromisoformat(f["upload_time_iso_8601"].replace("Z", "+00:00"))
        for files in meta.get("releases", {}).values()
        for f in files
        if "upload_time_iso_8601" in f
    ]
    return min(times) if times else None


@register
class DependencyVerifier(Verifier):
    """Hallucinated / squattable dependency check on imports added by the diff."""

    name = "deps"

    def run(self, ctx: RunContext) -> VerifierResult:
        result = VerifierResult(verifier=self.name, verdict=Verdict.PASS)

        # top-level modules imported on added lines
        new_imports: dict[str, tuple[str, int]] = {}
        for fd in ctx.diff.files:
            if not fd.is_python:
                continue
            for line_no, text in fd.added_text:
                m = _IMPORT_RE.match(text)
                if m:
                    new_imports.setdefault(m.group(1), (fd.path, line_no))

        local_modules = {
            p.stem for p in ctx.repo.glob("*") if p.suffix == ".py" or (p / "__init__.py").exists()
        }
        local_modules |= {p.parent.name for p in ctx.repo.glob("*/__init__.py")}

        checked = 0
        offline = False
        for mod, (path, line) in sorted(new_imports.items()):
            if mod in sys.stdlib_module_names or mod in local_modules:
                continue
            dist = _IMPORT_TO_DIST.get(mod, mod)
            meta = _fetch_pypi(dist)
            checked += 1
            if meta is None:
                offline = True
                continue
            if meta == {}:
                result.findings.append(
                    Finding(
                        verifier=self.name,
                        severity=Severity.BLOCK,
                        message=f"import `{mod}`: package `{dist}` does not exist on PyPI "
                        "(likely hallucinated — and a squattable name)",
                        file=path,
                        line=line,
                    )
                )
                continue
            first = _first_upload(meta)
            now = datetime.now(timezone.utc)
            if first and (now - first).days < _NEW_PACKAGE_DAYS:
                result.findings.append(
                    Finding(
                        verifier=self.name,
                        severity=Severity.WARN,
                        message=f"import `{mod}`: package `{dist}` first published only "
                        f"{(now - first).days} days ago — verify it is the intended package",
                        file=path,
                        line=line,
                    )
                )
            close = difflib.get_close_matches(dist.lower(), _POPULAR, n=1, cutoff=0.85)
            if close and close[0] != dist.lower():
                result.findings.append(
                    Finding(
                        verifier=self.name,
                        severity=Severity.WARN,
                        message=f"import `{mod}`: `{dist}` is suspiciously close to popular "
                        f"package `{close[0]}` — possible typo/squat",
                        file=path,
                        line=line,
                    )
                )

        result.metrics = {"new_imports_checked": checked}
        if offline and checked:
            result.verdict = Verdict.SKIP
            result.note = "PyPI unreachable; dependency check incomplete"
        elif any(f.severity == Severity.BLOCK for f in result.findings):
            result.verdict = Verdict.BLOCK
        elif result.findings:
            result.verdict = Verdict.WARN
        return result
