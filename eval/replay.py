#!/usr/bin/env python3
"""Replay harness: run `vouch check` over every corpus sample and record which
verifiers flag the known-bad change.

Per sample:
  merged_then_reverted → worktree at the buggy commit C, gate diff parent(C)..C
  regression_fix       → worktree at fix F, `git revert` F to recreate the buggy
                         change as a new commit, gate diff F..revert

Each sample gets its own venv with the target repo pip-installed editable, so
mutation/tautology run the repo's real test suite (in-place mode). Environments
that fail to build or whose suite is red at HEAD are recorded as such — that is
data, not noise: it bounds which verifiers are runnable per sample.

Usage:
  python eval/replay.py --corpus eval/corpus --clones eval/.clones \
      --out eval/results/replay.json [--limit N] [--sample REPO/SHA12]
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

VOUCH = shutil.which("vouch") or str(Path(sys.executable).with_name("vouch"))
DEFAULT_VERIFIERS = "deps,mutation,tautology"
TEST_VERIFIERS = {"mutation", "tautology"}  # need a per-sample environment
ENV_SETUP_TIMEOUT = 300
VOUCH_TIMEOUT = 900


def sh(cmd: list[str], cwd: Path | None = None, timeout: int = 120) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
        return proc.returncode, (proc.stdout + proc.stderr)
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s"


def build_env(wt: Path) -> tuple[str, str]:
    """Create a venv and install the target editable + test tooling.
    Returns (python_path, error) — error empty on success."""
    venv = wt / ".vouch-venv"
    code, out = sh([sys.executable, "-m", "venv", str(venv)], timeout=120)
    if code != 0:
        return "", f"venv creation failed: {out[-300:]}"
    py = str(venv / "bin" / "python")
    code, out = sh(
        [py, "-m", "pip", "install", "-q", "--disable-pip-version-check",
         "setuptools", "wheel", "pytest", "pytest-cov", "coverage"],
        timeout=ENV_SETUP_TIMEOUT,
    )
    if code != 0:
        return "", f"tooling install failed: {out[-300:]}"
    code, out = sh(
        [py, "-m", "pip", "install", "-q", "--disable-pip-version-check", "-e", "."],
        cwd=wt, timeout=ENV_SETUP_TIMEOUT,
    )
    if code != 0:
        return "", f"editable install failed: {out[-300:]}"
    return py, ""


def replay_sample(meta: dict, clone: Path, scratch: Path, verifiers: str) -> dict:
    record = {
        "repo": meta["repo"],
        "sha": meta["sha"],
        "kind": meta["kind"],
        "subject": meta["subject"],
        "status": "",
        "verifiers": {},
        "overall": None,
        "seconds": 0.0,
    }
    t0 = time.monotonic()
    wt = scratch / "wt"
    try:
        sha = meta["sha"]
        code, out = sh(
            ["git", "-C", str(clone), "worktree", "add", "--detach", str(wt), sha],
            timeout=120,
        )
        if code != 0:
            record["status"] = f"worktree failed: {out[-200:]}"
            return record

        if meta["kind"] == "regression_fix":
            # recreate the buggy change: revert the fix on top of it
            sh(["git", "-C", str(wt), "config", "user.email", "replay@vouch"], timeout=30)
            sh(["git", "-C", str(wt), "config", "user.name", "vouch-replay"], timeout=30)
            code, out = sh(["git", "-C", str(wt), "revert", "--no-edit", sha], timeout=120)
            if code != 0:
                record["status"] = "revert conflict"
                return record
            base = sha
        else:
            base = f"{sha}^"

        if TEST_VERIFIERS & set(verifiers.split(",")):
            py, env_err = build_env(wt)
            record["env"] = "ok" if not env_err else env_err
        else:
            py, env_err = "", ""
            record["env"] = "not needed"
        vbom_path = scratch / "vbom.json"
        cmd = [
            VOUCH, "check", "--repo", str(wt), "--base", base, "--all-code",
            "--in-place", "--verifiers", verifiers, "--vbom", str(vbom_path),
        ]
        if py:
            cmd += ["--python", py]
        code, out = sh(cmd, timeout=VOUCH_TIMEOUT)
        record["exit_code"] = code
        if not vbom_path.exists():
            record["status"] = f"vouch produced no VBOM: {out[-300:]}"
            return record
        vbom = json.loads(vbom_path.read_text())
        pred = vbom["predicate"]
        record["overall"] = pred["verdict"]
        for v in pred["verifiers"]:
            record["verifiers"][v["name"]] = {
                "verdict": v["verdict"],
                "findings": len(v["findings"]),
                "note": v["note"],
                "metrics": v["metrics"],
            }
        record["status"] = "ok"
        return record
    finally:
        record["seconds"] = round(time.monotonic() - t0, 1)
        sh(["git", "-C", str(clone), "worktree", "remove", "--force", str(wt)], timeout=60)
        sh(["git", "-C", str(clone), "worktree", "prune"], timeout=30)
        shutil.rmtree(wt, ignore_errors=True)


def summarize(records: list[dict], verifiers: str) -> dict:
    def flagged(v):
        return v and v["verdict"] in ("block", "warn")

    total = len(records)
    ok = [r for r in records if r["status"] == "ok"]
    summary = {
        "samples": total,
        "replayed_ok": len(ok),
        "env_ok": sum(1 for r in ok if r.get("env") == "ok"),
        "flagged_any": sum(
            1 for r in ok if any(flagged(v) for v in r["verifiers"].values())
        ),
        "per_verifier": {},
    }
    for name in verifiers.split(","):
        runs = [r["verifiers"].get(name) for r in ok]
        runs = [v for v in runs if v]
        summary["per_verifier"][name] = {
            "ran": sum(1 for v in runs if v["verdict"] not in ("skip", "error")),
            "flagged": sum(1 for v in runs if flagged(v)),
            "skip": sum(1 for v in runs if v["verdict"] == "skip"),
            "error": sum(1 for v in runs if v["verdict"] == "error"),
        }
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="eval/corpus")
    ap.add_argument("--clones", default="eval/.clones")
    ap.add_argument("--out", default="eval/results/replay.json")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sample", default="", help="replay one sample: <owner__repo>/<sha12>")
    ap.add_argument("--verifiers", default=DEFAULT_VERIFIERS)
    ap.add_argument("--sleep", type=float, default=0.0,
                    help="pause between samples (rate-limit courtesy for API verifiers)")
    ap.add_argument("--resume", action="store_true",
                    help="merge with existing --out file, re-running only samples whose "
                         "verifiers errored or are missing")
    args = ap.parse_args()

    corpus = Path(args.corpus)
    metas = sorted(corpus.glob("*/*/meta.json"))
    if args.sample:
        metas = [m for m in metas if args.sample in str(m)]
    if args.limit:
        metas = metas[: args.limit]

    records = []
    done: dict[str, dict] = {}
    if args.resume and Path(args.out).exists():
        prior = json.loads(Path(args.out).read_text())["records"]
        for r in prior:
            complete = (
                r["status"] == "ok"
                and r["verifiers"]
                and all(v["verdict"] != "error" for v in r["verifiers"].values())
            )
            if complete:
                done[r["sha"]] = r
        records.extend(done.values())
        print(f"resume: keeping {len(done)} completed samples")
    for i, meta_path in enumerate(metas, 1):
        meta = json.loads(meta_path.read_text())
        if meta["sha"] in done:
            continue
        clone = Path(args.clones) / meta["repo"].replace("/", "__")
        if not clone.exists():
            print(f"[{i}/{len(metas)}] {meta_path.parent.name} SKIP no clone")
            continue
        scratch = Path(tempfile.mkdtemp(prefix="vouch-replay-"))
        try:
            rec = replay_sample(meta, clone, scratch, args.verifiers)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        records.append(rec)
        if args.sleep:
            time.sleep(args.sleep)
        verdicts = {k: v["verdict"] for k, v in rec["verifiers"].items()}
        print(
            f"[{i}/{len(metas)}] {meta['repo']}@{meta['sha'][:12]} "
            f"{meta['kind']:<20} {rec['status']:<12} {verdicts} ({rec['seconds']}s)"
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    result = {"summary": summarize(records, args.verifiers), "records": records}
    out.write_text(json.dumps(result, indent=2) + "\n")
    print("\nsummary:", json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
