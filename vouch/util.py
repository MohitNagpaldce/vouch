from __future__ import annotations

import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path


def run_git(repo: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


@contextmanager
def work_dir(ctx):
    """The directory a test-touching verifier should operate in: the repo
    itself when ctx.in_place (harness mode), else a disposable worktree."""
    if ctx.in_place:
        yield ctx.repo
    else:
        with temp_worktree(ctx.repo, ctx.diff.head_ref) as wt:
            yield wt


@contextmanager
def temp_worktree(repo: Path, ref: str = "HEAD"):
    """Check out `ref` in a disposable worktree so verifiers never touch the
    user's working tree."""
    parent = Path(tempfile.mkdtemp(prefix="vouch-"))
    wt = parent / "wt"
    run_git(repo, "worktree", "add", "--detach", str(wt), ref)
    try:
        yield wt
    finally:
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "remove", "--force", str(wt)],
            capture_output=True,
        )
        shutil.rmtree(parent, ignore_errors=True)


def run_pytest(
    cwd: Path,
    python: str,
    targets: list[str] | None = None,
    timeout: float = 300.0,
    extra: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> tuple[int, str]:
    """Run pytest; returns (exit_code, output). Exit code 124 on timeout."""
    import os

    cmd = [python, "-m", "pytest", "-x", "-q", "--no-header", "-p", "no:cacheprovider"]
    cmd += extra or []
    cmd += targets or []
    full_env = {**os.environ, **(env or {})}
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=full_env
        )
        return proc.returncode, proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s"
