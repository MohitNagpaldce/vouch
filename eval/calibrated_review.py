#!/usr/bin/env python3
"""Calibrated-confidence review: instead of an adversarial PASS/attack framing,
ask the reviewer for a 0-100 likelihood that the change introduces a defect,
plus structured findings. Sweeping the likelihood threshold over the bad and
control corpora yields an ROC curve for LLM review as a detector.

Runs directly off the stored diff.patch files — no worktrees or environments.

Usage:
  python eval/calibrated_review.py --corpus eval/corpus --out eval/results/calib.json
  python eval/calibrated_review.py --corpus eval/corpus-control --out eval/results/calib-control.json
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from pathlib import Path

SYSTEM = """You are a careful senior reviewer estimating regression risk for a CI system.
Assess the diff and respond with JSON only:
{"defect_likelihood": <integer 0-100: probability this change introduces a defect
or will need to be reverted>, "findings": [{"file": str, "line": int|null,
"message": str} ...]}
Calibrate honestly: most merged changes are fine; reserve high likelihoods for
concrete, articulable defects. An empty findings list with a low likelihood is a
perfectly good answer."""

MAX_DIFF_CHARS = 60_000


def call_openai(model: str, diff_text: str, retries: int = 3) -> dict:
    body = json.dumps(
        {
            "model": model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Diff to assess:\n\n{diff_text}"},
            ],
        }
    ).encode()
    delay = 15.0
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=body,
                headers={
                    "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                    "content-type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read())
            return json.loads(data["choices"][0]["message"]["content"])
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default=os.environ.get("VOUCH_OPENAI_MODEL", "gpt-5.1"))
    ap.add_argument("--sleep", type=float, default=2.0)
    args = ap.parse_args()

    records = []
    metas = sorted(Path(args.corpus).glob("*/*/meta.json"))
    for i, mp in enumerate(metas, 1):
        meta = json.loads(mp.read_text())
        diff_text = (mp.parent / "diff.patch").read_text(errors="replace")[:MAX_DIFF_CHARS]
        rec = {"repo": meta["repo"], "sha": meta["sha"], "kind": meta["kind"],
               "subject": meta["subject"], "status": "ok",
               "likelihood": None, "findings": []}
        try:
            out = call_openai(args.model, diff_text)
            rec["likelihood"] = int(out.get("defect_likelihood", 0))
            rec["findings"] = out.get("findings", [])[:10]
        except Exception as exc:
            rec["status"] = f"error: {exc}"
        records.append(rec)
        print(f"[{i}/{len(metas)}] {meta['repo']}@{meta['sha'][:10]} "
              f"likelihood={rec['likelihood']} ({rec['status']})")
        time.sleep(args.sleep)

    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    ok = [r for r in records if r["status"] == "ok"]
    outp.write_text(json.dumps(
        {"model": args.model, "n": len(records), "ok": len(ok), "records": records},
        indent=2) + "\n")
    print(f"done: {len(ok)}/{len(records)} ok -> {outp}")


if __name__ == "__main__":
    main()
