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


def mine_repo(slug: str, repo: Path, out: Path, limit: int) -> dict:
    stats = {"merged_then_reverted": 0, "regression_fix": 0, "skipped": 0}
    log = git(repo, "log", "--format=%H%x01%s%x01%b%x02", "-n", "20000")
    entries = [e.split("\x01") for e in log.split("\x02") if e.strip()]

    candidates: list[tuple[str, str, str]] = []  # (sha, kind, subject)
    for entry in entries:
        if len(entry) != 3:
            continue
        sha, subject, body = (x.strip() for x in entry)
        m = REVERT_RE.search(body)
        if subject.lower().startswith("revert") and m:
            candidates.append((m.group(1), "merged_then_reverted", subject))
        elif REGRESSION_RE.search(subject):
            candidates.append((sha, "regression_fix", subject))

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
            all_stats[slug] = mine_repo(slug, repo, out, args.limit)
        except Exception as exc:
            all_stats[slug] = {"error": str(exc)}
        print(f"  {all_stats[slug]}")

    (out / "stats.json").write_text(json.dumps(all_stats, indent=2) + "\n")
    total = sum(
        s.get("reverted", 0) + s.get("regression_fix", 0) + s.get("merged_then_reverted", 0)
        for s in all_stats.values()
    )
    print(f"\ncorpus samples: {total} → {out}")


if __name__ == "__main__":
    main()
