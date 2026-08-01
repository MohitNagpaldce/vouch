from __future__ import annotations

import time

from ..coverage_map import COV_ENV, COV_EXTRA, build_map, cov_available, tests_for_line
from ..models import Finding, RunContext, Severity, Verdict, VerifierResult
from ..mutants import collect_sites, make_mutant
from ..util import run_pytest, temp_worktree
from .base import Verifier, register

_DEFAULT_MAX_MUTANTS = 30
_DEFAULT_MIN_SCORE = 0.5


@register
class MutationVerifier(Verifier):
    """Diff-scoped mutation testing: seed small faults into the changed lines
    and check the diff's tests notice. Surviving mutants = untested behavior.

    When pytest-cov is available in the target environment, a per-test coverage
    map from the baseline run scopes each mutant's run to only the tests that
    execute the mutated line; mutants on lines no test executes survive
    trivially and are reported as uncovered."""

    name = "mutation"

    def run(self, ctx: RunContext) -> VerifierResult:
        result = VerifierResult(verifier=self.name, verdict=Verdict.PASS)
        targets = [f for f in ctx.diff.python_impl_files if f.changed_lines]
        if not targets:
            result.verdict = Verdict.SKIP
            result.note = "no changed Python implementation lines to mutate"
            return result

        max_mutants = int(ctx.config.get("max_mutants", _DEFAULT_MAX_MUTANTS))
        min_score = float(ctx.tier_config.get("min_mutation_score", _DEFAULT_MIN_SCORE))

        with temp_worktree(ctx.repo, ctx.diff.head_ref) as wt:
            scoped = cov_available(ctx.python)
            t0 = time.monotonic()
            code, out = run_pytest(
                wt,
                ctx.python,
                extra=COV_EXTRA if scoped else None,
                env=COV_ENV if scoped else None,
            )
            if scoped and code == 4:  # usage error (e.g. cov plugin conflict): retry plain
                scoped = False
                code, out = run_pytest(wt, ctx.python)
            baseline_s = time.monotonic() - t0
            if code == 5:  # pytest: no tests collected
                result.verdict = Verdict.BLOCK
                result.findings.append(
                    Finding(
                        verifier=self.name,
                        severity=Severity.BLOCK,
                        message="no tests collected — the diff has no executable test evidence",
                    )
                )
                return result
            if code != 0:
                result.verdict = Verdict.ERROR
                result.note = f"test suite fails at HEAD (exit {code}); fix tests before gating"
                return result

            cmap = build_map(wt, ctx.python) if scoped else None
            per_mutant_timeout = max(20.0, baseline_s * 3)
            killed = survived = uncovered = 0
            tests_run_total = 0

            for fd in targets:
                path = wt / fd.path
                source = path.read_text()
                try:
                    sites = collect_sites(source, fd.changed_lines)
                except SyntaxError:
                    continue
                if len(sites) > max_mutants:
                    all_sites = len(sites)
                    step = all_sites / max_mutants
                    sites = [sites[int(i * step)] for i in range(max_mutants)]
                    result.note = f"sampled {max_mutants} of {all_sites} mutation sites"
                for spec in sites:
                    selected: list[str] | None = None
                    if cmap is not None:
                        nodes = tests_for_line(cmap, fd.path, spec.line)
                        if not nodes:
                            survived += 1
                            uncovered += 1
                            result.findings.append(
                                Finding(
                                    verifier=self.name,
                                    severity=Severity.WARN,
                                    message=f"uncovered mutant: {spec.description} — "
                                    "no test executes this changed line at all",
                                    file=fd.path,
                                    line=spec.line,
                                )
                            )
                            continue
                        selected = sorted(nodes)
                        tests_run_total += len(selected)
                    mutated = make_mutant(source, fd.changed_lines, spec.index)
                    path.write_text(mutated)
                    code, _ = run_pytest(
                        wt, ctx.python, targets=selected, timeout=per_mutant_timeout
                    )
                    path.write_text(source)
                    if code == 0:
                        survived += 1
                        result.findings.append(
                            Finding(
                                verifier=self.name,
                                severity=Severity.WARN,
                                message=f"surviving mutant: {spec.description} — "
                                "no test failed when this fault was injected",
                                file=fd.path,
                                line=spec.line,
                            )
                        )
                    else:  # non-zero exit, incl. timeout (=hang detected) counts as killed
                        killed += 1

        total = killed + survived
        score = killed / total if total else 1.0
        result.metrics = {
            "mutants": total,
            "killed": killed,
            "survived": survived,
            "uncovered": uncovered,
            "mutation_score": round(score, 3),
            "min_required": min_score,
            "baseline_test_s": round(baseline_s, 2),
            "cov_scoped": cmap is not None,
        }
        if total == 0:
            result.verdict = Verdict.SKIP
            result.note = "no mutable expressions on changed lines"
        elif score < min_score:
            result.verdict = Verdict.BLOCK
            result.findings.append(
                Finding(
                    verifier=self.name,
                    severity=Severity.BLOCK,
                    message=f"mutation score {score:.0%} below required {min_score:.0%} "
                    f"({survived}/{total} injected faults went undetected by the tests)",
                )
            )
        elif survived:
            result.verdict = Verdict.WARN
        return result
