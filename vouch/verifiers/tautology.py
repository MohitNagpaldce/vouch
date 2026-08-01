from __future__ import annotations

from ..models import Finding, RunContext, Severity, Verdict, VerifierResult
from ..util import run_git, run_pytest, work_dir
from .base import Verifier, register


@register
class TautologyVerifier(Verifier):
    """A test added alongside an implementation change should FAIL when run
    against the OLD implementation — otherwise it doesn't test the change.
    Runs the diff's new/changed test files against the merge-base version of
    the changed implementation files, in a disposable worktree."""

    name = "tautology"

    def run(self, ctx: RunContext) -> VerifierResult:
        result = VerifierResult(verifier=self.name, verdict=Verdict.PASS)
        test_files = ctx.diff.python_test_files
        impl_files = ctx.diff.python_impl_files
        if not test_files:
            result.verdict = Verdict.SKIP
            result.note = "diff adds/changes no test files"
            return result
        if not impl_files:
            result.verdict = Verdict.SKIP
            result.note = "tests-only diff; nothing to compare against base"
            return result

        with work_dir(ctx) as wt:
            targets = [f.path for f in test_files if (wt / f.path).exists()]
            if not targets:
                result.verdict = Verdict.SKIP
                result.note = "changed test files not found at HEAD"
                return result

            # sanity: the new tests must pass at HEAD
            code, out = run_pytest(wt, ctx.python, targets=targets)
            if code != 0:
                result.verdict = Verdict.ERROR
                result.note = f"diff's own tests fail at HEAD (exit {code})"
                return result

            # revert implementation (not tests) to merge-base
            for fd in impl_files:
                if fd.is_new:
                    (wt / fd.path).unlink(missing_ok=True)
                else:
                    run_git(wt, "checkout", ctx.diff.merge_base, "--", fd.path)

            try:
                code, out = run_pytest(wt, ctx.python, targets=targets)
            finally:
                # restore HEAD state (matters in in_place mode, harmless otherwise)
                run_git(wt, "checkout", ctx.diff.head_ref, "--", ".", check=False)

        if code == 0:
            for fd in test_files:
                result.findings.append(
                    Finding(
                        verifier=self.name,
                        severity=Severity.BLOCK,
                        message="tautological tests: every test in this file also passes "
                        "against the PRE-change implementation — the tests do not "
                        "verify the change they accompany",
                        file=fd.path,
                    )
                )
            result.verdict = Verdict.BLOCK
        result.metrics = {
            "test_files": len(test_files),
            "old_impl_exit_code": code,
        }
        return result
