from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .gitdiff import load_diff
from .models import RunContext, Severity, Verdict
from .policy import DEFAULT_POLICY, load_policy
from .provenance import detect_provenance
from .vbom import build_vbom, write_vbom
from .verifiers import REGISTRY

_ICON = {
    Verdict.PASS: "✓",
    Verdict.WARN: "⚠",
    Verdict.BLOCK: "✗",
    Verdict.SKIP: "–",
    Verdict.ERROR: "!",
}


def _aggregate(verdicts: list[Verdict]) -> Verdict:
    if Verdict.BLOCK in verdicts:
        return Verdict.BLOCK
    if Verdict.ERROR in verdicts:
        return Verdict.ERROR
    if Verdict.WARN in verdicts:
        return Verdict.WARN
    if all(v == Verdict.SKIP for v in verdicts) and verdicts:
        return Verdict.SKIP
    return Verdict.PASS


def check(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    policy = load_policy(repo)
    diff = load_diff(repo, args.base)
    if not diff.files:
        print(f"vouch: no changes between {args.base} and HEAD — nothing to verify")
        return 0

    provenance = detect_provenance(repo, diff.merge_base)
    if args.assume_ai and not provenance.is_ai:
        provenance.is_ai = True
        provenance.evidence.append("--assume-ai flag")

    tier = policy.tier_for([f.path for f in diff.files])
    ctx = RunContext(
        repo=repo,
        diff=diff,
        provenance=provenance,
        tier_name=tier.name,
        tier_config=tier.config,
        in_place=args.in_place,
    )
    if args.python:
        ctx.python = args.python

    if not provenance.is_ai and not args.all_code:
        print(
            "vouch: no AI provenance detected in this diff "
            "(use --assume-ai or --all-code to verify anyway)"
        )
        return 0

    names = args.verifiers.split(",") if args.verifiers else tier.verifiers
    print(f"vouch {__version__} · tier: {tier.name} · "
          f"provenance: {', '.join(provenance.models) or 'unknown/assumed'}")
    print(f"diff: {diff.merge_base[:12]}..HEAD · "
          f"{len(diff.files)} file(s) changed\n")

    results = []
    for name in names:
        cls = REGISTRY.get(name)
        if cls is None:
            print(f"  ? {name:<10} unknown verifier (available: {', '.join(REGISTRY)})")
            continue
        result = cls().timed_run(ctx)
        results.append(result)
        line = f"  {_ICON[result.verdict]} {name:<10} {result.verdict.value.upper():<6} ({result.duration_s}s)"
        if result.note:
            line += f"  {result.note}"
        if result.metrics:
            line += "  " + " ".join(f"{k}={v}" for k, v in result.metrics.items())
        print(line)
        for f in result.findings:
            loc = f":{f.line}" if f.line else ""
            where = f" [{f.file}{loc}]" if f.file else ""
            print(f"      {f.severity.value.upper()}{where} {f.message}")

    overall = _aggregate([r.verdict for r in results])
    print(f"\nverdict: {overall.value.upper()}")

    if args.vbom:
        vbom = build_vbom(ctx, results, overall)
        write_vbom(args.vbom, vbom)
        print(f"VBOM written to {args.vbom}")
    if args.json:
        print(json.dumps(build_vbom(ctx, results, overall), indent=2))

    if overall == Verdict.BLOCK:
        return 1
    if overall in (Verdict.WARN, Verdict.ERROR) and policy.fail_on == "warn":
        return 1
    return 0


def init(args: argparse.Namespace) -> int:
    target = Path(args.repo) / "vouch.toml"
    if target.exists() and not args.force:
        print(f"{target} already exists (use --force to overwrite)")
        return 1
    target.write_text(DEFAULT_POLICY)
    print(f"wrote {target}")
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="vouch",
        description="A verification gate for AI-generated code.",
    )
    parser.add_argument("--version", action="version", version=f"vouch {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="verify the current branch's diff")
    p_check.add_argument("--base", default="main", help="base ref to diff against (default: main)")
    p_check.add_argument("--repo", default=".", help="repository path (default: .)")
    p_check.add_argument("--verifiers", default="", help="comma-separated override of tier verifiers")
    p_check.add_argument("--vbom", default="", help="write VBOM attestation JSON to this path")
    p_check.add_argument("--json", action="store_true", help="print VBOM JSON to stdout")
    p_check.add_argument("--assume-ai", action="store_true",
                         help="treat the diff as AI-authored even without provenance markers")
    p_check.add_argument("--all-code", action="store_true",
                         help="verify regardless of AI provenance")
    p_check.add_argument("--python", default="",
                         help="interpreter used to run the target repo's tests "
                              "(default: the one running vouch)")
    p_check.add_argument("--in-place", action="store_true",
                         help="run test-touching verifiers directly in --repo instead of a "
                              "disposable worktree; ONLY safe if --repo is itself throwaway")
    p_check.set_defaults(func=check)

    p_init = sub.add_parser("init", help="write a default vouch.toml policy")
    p_init.add_argument("--repo", default=".", help="repository path (default: .)")
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=init)

    args = parser.parse_args(argv)
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
