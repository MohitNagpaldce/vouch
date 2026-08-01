#!/usr/bin/env python3
"""Mine real regression evidence from git history for the Vouch evaluation corpus.

Two sources of ground-truth buggy changes:
  1. Merged-then-reverted commits: a commit C that a later commit R reverts
     ("This reverts commit <sha>"). C is a change that shipped and turned out
     wrong — exactly what a verification gate should have caught.
  2. Regression-fix commits: a commit F whose subject declares it fixes a
     regression; reverse-applying F reconstructs the buggy state.

Output layout:
  corpus/<owner>__<repo>/<sha12>/diff.patch   # the buggy change itself
  corpus/<owner>__<repo>/<sha12>/meta.json    # provenance + classification
  corpus/stats.json                           # per-repo summary

Usage:
  python eval/mine_reverts.py --repos psf/requests pallets/click --out eval/corpus
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

REVERT_RE = re.compile(r"This reverts commit ([0-9a-f]{7,40})", re.IGNORECASE)
REGRESSION_RE = re.compile(r"\b(fix(es|ed)?\s+.{0,40}regression|regression.{0,40}fix)\b", re.IGNORECASE)
MAX_DIFF_LINES = 800


def git(repo: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])}... failed: {proc.stderr[:200]}")
    return proc.stdout


def clone(slug: str, workdir: Path) -> Path:
    dest = workdir / slug.replace("/", "__")
    if not dest.exists():
        subprocess.run(
            ["git", "clone", "--filter=blob:none", "--quiet",
             f"https://github.com/{slug}.git", str(dest)],
            check=True,
        )
    return dest


def commit_diff(repo: Path, sha: str) -> str:
    return git(repo, "show", "--no-color", "--format=", sha, check=False)


def touched_py(diff: str) -> tuple[list[str], list[str]]:
    impl, tests = [], []
    for m in re.finditer(r"^\+\+\+ b/(.+)$", diff, re.MULTILINE):
        path = m.group(1)
        if not path.endswith(".py"):
            continue
        name = Path(path).name
        if name.startswith("test_") or name.endswith("_test.py") or "tests/" in path:
            tests.append(path)
        else:
            impl.append(path)
    return impl, tests


def mine_repo(slug: str, repo: Path, out: Path, limit: int, control: bool = False) -> dict:
    stats = {"merged_then_reverted": 0, "regression_fix": 0, "control_good": 0, "skipped": 0}
    log = git(repo, "log", "--format=%H%x01%s%x01%b%x01%at%x02", "-n", "20000")
    entries = [e.split("\x01") for e in log.split("\x02") if e.strip()]

    bad_shas: set[str] = set()
    candidates: list[tuple[str, str, str]] = []  # (sha, kind, subject)
    for entry in entries:
        if len(entry) != 4:
            continue
        sha, subject, body, ts = (x.strip() for x in entry)
        m = REVERT_RE.search(body)
        if subject.lower().startswith("revert") and m:
            candidates.append((m.group(1), "merged_then_reverted", subject))
            bad_shas.update({sha, m.group(1)})
        elif REGRESSION_RE.search(subject):
            candidates.append((sha, "regression_fix", subject))
            bad_shas.add(sha)

    if control:
        # presumed-good arm: aged ≥ 1 year, never reverted, not a revert/fix
        # itself; deterministic stride sampling for reproducibility
        import time as _time

        year_ago = _time.time() - 365 * 86400
        good = [
            (sha, "control_good", subject)
            for sha, subject, body, ts in (
                tuple(x.strip() for x in e) for e in entries if len(e) == 4
            )
            if sha not in bad_shas
            and ts.isdigit()
            and int(ts) < year_ago
            and not subject.lower().startswith(("revert", "merge"))
        ]
        stride = max(1, len(good) // (limit * 3))  # oversample; size filters prune
        candidates = good[::stride]

    kept = 0
    for sha, kind, subject in candidates:
        if kept >= limit:
            break
        diff = commit_diff(repo, sha)
        if not diff or len(diff.splitlines()) > MAX_DIFF_LINES:
            stats["skipped"] += 1
            continue
        impl, tests = touched_py(diff)
        if not impl:
            stats["skipped"] += 1
            continue
        meta_raw = git(repo, "show", "-s", "--format=%H%x01%s%x01%an%x01%aI", sha, check=False)
        if not meta_raw.strip():
            stats["skipped"] += 1
            continue
        full_sha, full_subject, author, date = meta_raw.strip().split("\x01")
        dest = out / slug.replace("/", "__") / full_sha[:12]
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "diff.patch").write_text(diff)
        (dest / "meta.json").write_text(
            json.dumps(
                {
                    "repo": slug,
                    "sha": full_sha,
                    "kind": kind,
                    "subject": full_subject,
                    "evidence_subject": subject,
                    "author": author,
                    "date": date,
                    "impl_files": impl,
                    "test_files": tests,
                    "diff_lines": len(diff.splitlines()),
                },
                indent=2,
            )
            + "\n"
        )
        stats[kind if kind in stats else "skipped"] += 1
        kept += 1
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos", nargs="+", required=True, help="owner/name slugs")
    ap.add_argument("--out", default="eval/corpus")
    ap.add_argument("--limit", type=int, default=50, help="max samples per repo")
    ap.add_argument("--workdir", default="", help="clone cache dir (default: temp)")
    ap.add_argument("--control", action="store_true",
                    help="mine presumed-GOOD commits (aged, never reverted) instead")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    workdir = Path(args.workdir) if args.workdir else Path(tempfile.mkdtemp(prefix="vouch-mine-"))
    workdir.mkdir(parents=True, exist_ok=True)

    all_stats: dict[str, dict] = {}
    for slug in args.repos:
        print(f"mining {slug} ...")
        try:
            repo = clone(slug, workdir)
            all_stats[slug] = mine_repo(slug, repo, out, args.limit, control=args.control)
        except Exception as exc:
            all_stats[slug] = {"error": str(exc)}
        print(f"  {all_stats[slug]}")

    (out / "stats.json").write_text(json.dumps(all_stats, indent=2) + "\n")
    total = sum(
        s.get("regression_fix", 0) + s.get("merged_then_reverted", 0) + s.get("control_good", 0)
        for s in all_stats.values()
    )
    print(f"\ncorpus samples: {total} → {out}")


if __name__ == "__main__":
    main()
