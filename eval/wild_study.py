#!/usr/bin/env python3
"""Wild AI-PR study: find real, merged, AI-co-authored commits on GitHub and
measure their verification adequacy with the vouch gate.

Phase 1 (search): GitHub commit search for AI co-author trailers.
Phase 2 (gate):   clone, worktree at the commit, per-repo venv (modern repos,
                  so environments mostly build), vouch deps+mutation+tautology
                  against the commit's parent.

Usage:
  python eval/wild_study.py search --out eval/results/wild-commits.json --per-marker 60
  python eval/wild_study.py gate --commits eval/results/wild-commits.json \
      --out eval/results/wild.json [--limit N]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOUCH = str(Path(sys.executable).with_name("vouch"))

MARKERS = {
    "anthropic/claude": '"Co-authored-by: Claude"',
    "openai/copilot": '"Co-authored-by: Copilot"',
}


def sh(cmd: list[str], cwd: Path | None = None, timeout: int = 300) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return p.returncode, p.stdout + p.stderr
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def search(per_marker: int, out: Path) -> None:
    found = []
    for family, marker in MARKERS.items():
        page = 1
        got = 0
        while got < per_marker and page <= 10:
            code, txt = sh(["gh", "api", "-X", "GET", "search/commits",
                            "-f", f"q={marker} language:python merge:false",
                            "-f", "per_page=30", "-f", f"page={page}",
                            "--jq", ".items"])
            if code != 0:
                if "rate limit" in txt.lower():
                    print(f"  rate limited on p{page}; waiting 70s")
                    time.sleep(70)
                    continue
                print(f"  search error p{page}: {txt[:100]}")
                break
            items = json.loads(txt or "[]")
            if not items:
                break
            for it in items:
                repo = it["repository"]
                if repo.get("fork") or repo.get("private"):
                    continue
                found.append({
                    "family": family,
                    "repo": repo["full_name"],
                    "sha": it["sha"],
                    "date": it["commit"]["author"]["date"],
                    "subject": it["commit"]["message"].splitlines()[0][:100],
                })
                got += 1
                if got >= per_marker:
                    break
            page += 1
            time.sleep(10)
        print(f"{family}: {got} commits")
    out.write_text(json.dumps(found, indent=2) + "\n")
    print(f"{len(found)} -> {out}")


def build_env(wt: Path) -> tuple[str, str]:
    venv = wt / ".vouch-venv"
    code, out = sh([sys.executable, "-m", "venv", str(venv)], timeout=120)
    if code != 0:
        return "", "venv failed"
    py = str(venv / "bin" / "python")
    code, out = sh([py, "-m", "pip", "install", "-q", "--disable-pip-version-check",
                    "setuptools", "wheel", "pytest", "pytest-cov", "coverage"],
                   timeout=300)
    if code != 0:
        return "", "tooling install failed"
    code, out = sh([py, "-m", "pip", "install", "-q", "--disable-pip-version-check",
                    "-e", "."], cwd=wt, timeout=300)
    if code != 0:
        return py, "editable install failed"  # still usable for standalone repos
    return py, ""


def gate(commits: list[dict], out: Path, limit: int) -> None:
    clones = ROOT / "eval" / ".wild-clones"
    clones.mkdir(parents=True, exist_ok=True)
    records = []
    todo = commits[:limit] if limit else commits
    for i, c in enumerate(todo, 1):
        rec = dict(c)
        rec["status"] = ""
        rec["verifiers"] = {}
        clone = clones / c["repo"].replace("/", "__")
        scratch = Path(tempfile.mkdtemp(prefix="vouch-wild-"))
        wt = scratch / "wt"
        try:
            if not clone.exists():
                code, outp = sh(["git", "clone", "--filter=blob:none", "--quiet",
                                 f"https://github.com/{c['repo']}.git", str(clone)],
                                timeout=300)
                if code != 0:
                    rec["status"] = "clone failed"
                    continue
            code, outp = sh(["git", "-C", str(clone), "worktree", "add",
                             "--detach", str(wt), c["sha"]], timeout=120)
            if code != 0:
                sh(["git", "-C", str(clone), "fetch", "--quiet", "origin", c["sha"]],
                   timeout=120)
                code, outp = sh(["git", "-C", str(clone), "worktree", "add",
                                 "--detach", str(wt), c["sha"]], timeout=120)
                if code != 0:
                    rec["status"] = "commit unreachable"
                    continue
            py, env_err = build_env(wt)
            rec["env"] = env_err or "ok"
            vbom = scratch / "vbom.json"
            cmd = [VOUCH, "check", "--repo", str(wt), "--base", f"{c['sha']}^",
                   "--in-place", "--verifiers", "deps,mutation,tautology",
                   "--vbom", str(vbom)]
            if py:
                cmd += ["--python", py]
            code, outp = sh(cmd, timeout=900)
            if not vbom.exists():
                rec["status"] = f"no vbom: {outp[-150:]}"
                continue
            pred = json.loads(vbom.read_text())["predicate"]
            rec["status"] = "ok"
            rec["provenance"] = pred["provenance"]["models"]
            rec["overall"] = pred["verdict"]
            for v in pred["verifiers"]:
                rec["verifiers"][v["name"]] = {"verdict": v["verdict"],
                                               "metrics": v["metrics"],
                                               "note": v["note"]}
        finally:
            sh(["git", "-C", str(clone), "worktree", "remove", "--force", str(wt)],
               timeout=60)
            sh(["git", "-C", str(clone), "worktree", "prune"], timeout=30)
            shutil.rmtree(scratch, ignore_errors=True)
            records.append(rec)
            mv = rec["verifiers"].get("mutation", {})
            print(f"[{i}/{len(todo)}] {c['repo']}@{c['sha'][:8]} {rec['status']:<10} "
                  f"env={rec.get('env','-'):<24} mut={mv.get('verdict','-')} "
                  f"{mv.get('metrics',{}).get('mutation_score','')}")
            out.write_text(json.dumps({"records": records}, indent=2) + "\n")
    print("done ->", out)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("--out", required=True)
    s.add_argument("--per-marker", type=int, default=60)
    g = sub.add_parser("gate")
    g.add_argument("--commits", required=True)
    g.add_argument("--out", required=True)
    g.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    if args.cmd == "search":
        search(args.per_marker, Path(args.out))
    else:
        commits = json.loads(Path(args.commits).read_text())
        gate(commits, Path(args.out), args.limit)


if __name__ == "__main__":
    main()
