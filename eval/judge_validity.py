#!/usr/bin/env python3
"""Finding-level validity: when a reviewer flags a known-bad diff, do its
findings describe the defect that actually caused the revert/regression — or
incidental issues (right verdict, wrong reason)?

Judge: LLM comparing the reviewer's findings against the ground-truth evidence
(the revert subject for merged-then-reverted samples; the fix subject for
regression fixes — which names the regression). Verdicts: "identifies" (a
finding describes the actual defect), "incidental" (findings are plausible but
unrelated to the actual defect), "none" (no findings).

Caveat recorded in output: judge family may equal reviewer family.

Usage:
  python eval/judge_validity.py --calib eval/results/calib.json \
      --corpus eval/corpus --out eval/results/validity.json
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from pathlib import Path

SYSTEM = """You judge code-review findings against ground truth. You are given:
(1) findings a reviewer produced for a code change, and (2) ground-truth
evidence of why that change was actually bad (it was later reverted, or a
later commit fixed the regression it introduced; the evidence is that later
commit's subject line). Respond JSON only:
{"verdict": "identifies" | "incidental", "reason": "<one sentence>"}
"identifies" = at least one finding plausibly describes the same defect the
ground truth points to. "incidental" = the findings, even if individually
plausible, concern different issues than the actual defect."""


def call_judge(model: str, payload: str, retries: int = 3) -> dict:
    body = json.dumps(
        {
            "model": model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": payload},
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
            with urllib.request.urlopen(req, timeout=120) as resp:
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
    ap.add_argument("--calib", required=True)
    ap.add_argument("--corpus", default="eval/corpus")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="gpt-5.1")
    ap.add_argument("--sleep", type=float, default=2.0)
    args = ap.parse_args()

    calib = json.loads(Path(args.calib).read_text())
    metas = {}
    for mp in Path(args.corpus).glob("*/*/meta.json"):
        m = json.loads(mp.read_text())
        metas[m["sha"]] = m

    records = []
    todo = [r for r in calib["records"] if r["status"] == "ok" and r["findings"]]
    for i, r in enumerate(todo, 1):
        meta = metas.get(r["sha"], {})
        if meta.get("kind") == "regression_fix":
            truth = f"A later commit fixed the regression this change introduced: {meta.get('subject','')!r}"
        else:
            truth = f"This change was later reverted: {meta.get('evidence_subject', meta.get('subject',''))!r}"
        payload = (
            f"Reviewer findings:\n{json.dumps(r['findings'], indent=1)}\n\n"
            f"Ground truth: {truth}"
        )
        rec = {"repo": r["repo"], "sha": r["sha"], "kind": r["kind"],
               "likelihood": r["likelihood"], "n_findings": len(r["findings"]),
               "verdict": None, "reason": ""}
        try:
            out = call_judge(args.model, payload)
            rec["verdict"] = out.get("verdict")
            rec["reason"] = out.get("reason", "")
        except Exception as exc:
            rec["verdict"] = f"error: {exc}"
        records.append(rec)
        print(f"[{i}/{len(todo)}] {r['repo']}@{r['sha'][:10]} -> {rec['verdict']}")
        time.sleep(args.sleep)

    from collections import Counter
    counts = Counter(rec["verdict"] for rec in records)
    result = {
        "judge_model": args.model,
        "caveat": "judge family may equal reviewer family; ground truth is subject-line only",
        "no_findings": len([r for r in calib["records"] if r["status"] == "ok" and not r["findings"]]),
        "judged": len(records),
        "counts": dict(counts),
        "records": records,
    }
    Path(args.out).write_text(json.dumps(result, indent=2) + "\n")
    print("\n", json.dumps({k: v for k, v in result.items() if k != "records"}, indent=1))


if __name__ == "__main__":
    main()
