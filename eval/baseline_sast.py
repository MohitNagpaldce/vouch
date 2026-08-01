#!/usr/bin/env python3
"""SAST baseline: does Bandit flag the same corpus samples the LLM reviewer and
Vouch verifiers are measured on?

Per sample: worktree at the buggy state (same reconstruction as replay.py), run
Bandit on the changed implementation files, and count a sample as FLAGGED when
any finding lands on a line the diff changed. Reports sensitivity on the bad
corpus and false-positive rate on the control corpus.

Usage:
  python eval/baseline_sast.py --corpus eval/corpus --out eval/results/sast.json
  python eval/baseline_sast.py --corpus eval/corpus-control --out eval/results/sast-control.json
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from vouch.gitdiff import load_diff  # noqa: E402

BANDIT = str(Path(sys.executable).with_name("bandit"))


def sh(cmd: list[str], cwd: Path | None = None, timeout: int = 300) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
        return proc.returncode, proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def run_sample(meta: dict, clone: Path, scratch: Path) -> dict:
    rec = {"repo": meta["repo"], "sha": meta["sha"], "kind": meta["kind"],
           "status": "", "flagged": False, "findings_on_changed_lines": 0,
           "findings_total": 0}
    wt = scratch / "wt"
    try:
        sha = meta["sha"]
        code, out = sh(["git", "-C", str(clone), "worktree", "add", "--detach", str(wt), sha])
        if code != 0:
            rec["status"] = "worktree failed"
            return rec
        if meta["kind"] == "regression_fix":
            sh(["git", "-C", str(wt), "config", "user.email", "r@v"])
            sh(["git", "-C", str(wt), "config", "user.name", "v"])
            code, _ = sh(["git", "-C", str(wt), "revert", "--no-edit", sha])
            if code != 0:
                rec["status"] = "revert conflict"
                return rec
            base = sha
        else:
            base = f"{sha}^"

        diff = load_diff(wt, base)
        impl = [f for f in diff.python_impl_files if f.changed_lines and (wt / f.path).exists()]
        if not impl:
            rec["status"] = "no impl files"
            return rec

        code, out = sh([BANDIT, "-f", "json", "-q", *[str(wt / f.path) for f in impl]])
        try:
            report = json.loads(out[out.index("{"):])
        except (ValueError, json.JSONDecodeError):
            rec["status"] = f"bandit parse failure (exit {code})"
            return rec

        changed = {f.path: f.changed_lines for f in impl}
        on_changed = 0
        for res in report.get("results", []):
            rel = str(Path(res["filename"]).resolve().relative_to(wt.resolve()))
            if any(ln in changed.get(rel, set()) for ln in res.get("line_range", [])):
                on_changed += 1
        rec["findings_total"] = len(report.get("results", []))
        rec["findings_on_changed_lines"] = on_changed
        rec["flagged"] = on_changed > 0
        rec["status"] = "ok"
        return rec
    finally:
        sh(["git", "-C", str(clone), "worktree", "remove", "--force", str(wt)])
        sh(["git", "-C", str(clone), "worktree", "prune"])
        shutil.rmtree(wt, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="eval/corpus")
    ap.add_argument("--clones", default="eval/.clones")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    records = []
    metas = sorted(Path(args.corpus).glob("*/*/meta.json"))
    for i, mp in enumerate(metas, 1):
        meta = json.loads(mp.read_text())
        clone = Path(args.clones) / meta["repo"].replace("/", "__")
        if not clone.exists():
            continue
        scratch = Path(tempfile.mkdtemp(prefix="vouch-sast-"))
        try:
            rec = run_sample(meta, clone, scratch)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        records.append(rec)
        print(f"[{i}/{len(metas)}] {meta['repo']}@{meta['sha'][:10]} "
              f"{rec['status']:<16} flagged={rec['flagged']}")

    ok = [r for r in records if r["status"] == "ok"]
    summary = {
        "samples": len(records),
        "ran": len(ok),
        "flagged": sum(r["flagged"] for r in ok),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "records": records}, indent=2) + "\n")
    print("\nsummary:", json.dumps(summary))


if __name__ == "__main__":
    main()
