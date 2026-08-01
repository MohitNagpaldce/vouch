"""VBOM: Verification Bill of Materials — an in-toto-style attestation of the
verification evidence an (AI-authored) diff has survived. Unsigned in v0.1;
sigstore signing planned."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone

from . import __version__
from .models import RunContext, Verdict, VerifierResult

PREDICATE_TYPE = "https://github.com/MohitNagpaldce/vouch/vbom/v0.1"


def build_vbom(
    ctx: RunContext,
    results: list[VerifierResult],
    overall: Verdict,
) -> dict:
    diff_digest = hashlib.sha256(ctx.diff.raw.encode()).hexdigest()
    return {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [
            {
                "name": f"git-diff:{ctx.diff.merge_base[:12]}..{ctx.diff.head_ref}",
                "digest": {"sha256": diff_digest},
            }
        ],
        "predicateType": PREDICATE_TYPE,
        "predicate": {
            "tool": {"name": "vouch", "version": __version__},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "provenance": asdict(ctx.provenance),
            "policy_tier": ctx.tier_name,
            "verdict": overall.value,
            "verifiers": [
                {
                    "name": r.verifier,
                    "verdict": r.verdict.value,
                    "metrics": r.metrics,
                    "duration_s": r.duration_s,
                    "note": r.note,
                    "findings": [asdict(f) for f in r.findings],
                }
                for r in results
            ],
        },
    }


def write_vbom(path: str, vbom: dict) -> None:
    with open(path, "w") as fh:
        json.dump(vbom, fh, indent=2)
        fh.write("\n")
