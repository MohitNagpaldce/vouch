#!/usr/bin/env python3
"""AI-authored arm: measure the self-verification thesis on genuinely
AI-authored code, in today's environment (no era decay).

Pipeline per corpus sample (small diffs only):
  1. SPEC   — one model distills the historical change into a standalone,
              self-contained module spec (so no historical repo is needed).
  2. AUTHOR — each model family independently implements the spec as a module
              PLUS its own pytest suite (the self-verification setting).
  3. GATE   — the diff (impl+tests, AI provenance trailer) goes through vouch
              (deps, mutation, tautology) in a fresh mini-repo.

Output: per-family distribution of mutation adequacy of AI tests on AI code,
tautology rate, and generation failures.

Usage:
  python eval/ai_arm.py --n 25 --out eval/results/ai-arm.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOUCH = str(Path(sys.executable).with_name("vouch"))
MAX_DIFF_LINES = 150

SPEC_SYSTEM = """Distill a real code change into a SELF-CONTAINED programming task.
You get a diff and its commit subject from a real project. Produce JSON:
{"task": "<2-6 sentence spec of a standalone module capturing the same core
behavior, including the subtle condition the change addressed. No project
dependencies - stdlib only>", "module_hint": "<suggested function signature(s)>"}
The task must be implementable in one file with no third-party packages."""

AUTHOR_SYSTEM = """You are a coding agent. Implement the task as a Python module and
write a pytest test suite for it, as you would before opening a PR.
Respond JSON only: {"impl": "<complete impl.py source>", "tests": "<complete
test_impl.py source; import from impl>"}. Stdlib only."""


def openai_json(model: str, system: str, user: str, retries: int = 3) -> dict:
    body = json.dumps({
        "model": model,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
    }).encode()
    delay = 15.0
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions", data=body,
                headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                         "content-type": "application/json"})
            with urllib.request.urlopen(req, timeout=240) as resp:
                data = json.loads(resp.read())
            return json.loads(data["choices"][0]["message"]["content"])
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


def gemini_json(model: str, system: str, user: str, retries: int = 3) -> dict:
    body = json.dumps({
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"response_mime_type": "application/json"},
    }).encode()
    delay = 20.0
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                data=body,
                headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"],
                         "content-type": "application/json"})
            with urllib.request.urlopen(req, timeout=240) as resp:
                data = json.loads(resp.read())
            text = "".join(p.get("text", "")
                           for p in data["candidates"][0]["content"].get("parts", []))
            m = re.search(r"\{.*\}", text, re.DOTALL)
            return json.loads(m.group(0) if m else text)
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


FAMILIES = {
    "openai/gpt": lambda s, u: openai_json(
        os.environ.get("VOUCH_OPENAI_MODEL", "gpt-5.1"), s, u),
    "google/gemini": lambda s, u: gemini_json(
        os.environ.get("VOUCH_GEMINI_MODEL", "gemini-flash-latest"), s, u),
}
TRAILER = {"openai/gpt": "Co-Authored-By: Copilot <copilot@github.com>",
           "google/gemini": "Co-Authored-By: Gemini <gemini@google.com>"}


def sh(cmd: list[str], cwd: Path, timeout: int = 300) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return p.returncode, p.stdout + p.stderr


def gate(impl: str, tests: str, family: str, scratch: Path) -> dict:
    repo = scratch / "repo"
    repo.mkdir()
    sh(["git", "init", "-q", "-b", "main"], repo)
    sh(["git", "config", "user.email", "a@v"], repo)
    sh(["git", "config", "user.name", "v"], repo)
    (repo / "README.md").write_text("ai-arm sample\n")
    sh(["git", "add", "."], repo)
    sh(["git", "commit", "-qm", "base"], repo)
    sh(["git", "checkout", "-qb", "feature"], repo)
    (repo / "impl.py").write_text(impl)
    (repo / "test_impl.py").write_text(tests)
    sh(["git", "add", "."], repo)
    sh(["git", "commit", "-qm", f"implement task\n\n{TRAILER[family]}"], repo)
    vbom = scratch / "vbom.json"
    code, out = sh([VOUCH, "check", "--repo", str(repo), "--base", "main",
                    "--in-place", "--verifiers", "deps,mutation,tautology",
                    "--vbom", str(vbom)], repo, timeout=600)
    if not vbom.exists():
        return {"status": f"vouch failed: {out[-200:]}"}
    pred = json.loads(vbom.read_text())["predicate"]
    res = {"status": "ok", "overall": pred["verdict"], "verifiers": {}}
    for v in pred["verifiers"]:
        res["verifiers"][v["name"]] = {"verdict": v["verdict"], "metrics": v["metrics"]}
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="eval/corpus")
    ap.add_argument("--n", type=int, default=25)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    metas = []
    for mp in sorted(Path(args.corpus).glob("*/*/meta.json")):
        m = json.loads(mp.read_text())
        if m["diff_lines"] <= MAX_DIFF_LINES:
            metas.append(mp)
    stride = max(1, len(metas) // args.n)
    picked = metas[::stride][: args.n]

    records = []
    for i, mp in enumerate(picked, 1):
        meta = json.loads(mp.read_text())
        diff = (mp.parent / "diff.patch").read_text(errors="replace")
        rec = {"repo": meta["repo"], "sha": meta["sha"], "subject": meta["subject"],
               "spec": None, "families": {}}
        try:
            spec = openai_json(os.environ.get("VOUCH_OPENAI_MODEL", "gpt-5.1"),
                               SPEC_SYSTEM,
                               f"Subject: {meta['subject']}\n\nDiff:\n{diff[:20000]}")
            rec["spec"] = spec.get("task", "")[:2000]
        except Exception as exc:
            rec["spec_error"] = str(exc)
            records.append(rec)
            continue
        prompt = f"Task:\n{spec['task']}\n\nSignature hints: {spec.get('module_hint','')}"
        for family, call in FAMILIES.items():
            fam: dict = {}
            try:
                gen = call(AUTHOR_SYSTEM, prompt)
                impl, tests = gen.get("impl", ""), gen.get("tests", "")
                if not impl or not tests:
                    fam = {"status": "empty generation"}
                else:
                    scratch = Path(tempfile.mkdtemp(prefix="vouch-ai-"))
                    try:
                        fam = gate(impl, tests, family, scratch)
                    finally:
                        shutil.rmtree(scratch, ignore_errors=True)
            except Exception as exc:
                fam = {"status": f"generation error: {exc}"}
            rec["families"][family] = fam
            time.sleep(1)
        records.append(rec)
        summary = {f: rec["families"].get(f, {}).get("overall") for f in FAMILIES}
        print(f"[{i}/{len(picked)}] {meta['repo']}@{meta['sha'][:8]} {summary}")

    Path(args.out).write_text(json.dumps({"n": len(records), "records": records},
                                         indent=2) + "\n")
    print("done ->", args.out)


if __name__ == "__main__":
    main()
