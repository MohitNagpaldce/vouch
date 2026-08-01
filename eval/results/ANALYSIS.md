# Replay run 1 — 55 samples, 8 repos (2026-08-01)

First detection-rate measurement of the verifier set against real
merged-then-reverted (38) and regression-fix (17) changes. Raw per-sample data:
`replay.json`. Harness: `eval/replay.py` (per-sample venv, editable install,
in-place vouch run).

## Headline findings

**1. 45% of known-bad changes shipped with zero test changes (25/55).**
The strongest and simplest result: nearly half of the changes that real
maintainers merged and later had to undo touched no test file at all. A gate
that merely requires executable test evidence for the changed code would have
flagged every one. This number is independent of environment decay (it's a
diff property) and is the paper's most quotable statistic so far.

**2. Where the full gate could run, it caught the bad change.**
`pallets/click@e798f64` ("Use shlex.quote for quoting shell arguments",
merged 2020, later reverted) is the poster sample — all three verifiers fired:
- mutation: **11/11 mutants on the changed lines uncovered** — no test executed
  any changed line (the only accompanying test was an import-graph test).
- tautology: the accompanying test file **passes against the pre-change
  implementation** — it verified nothing about the change.
- deps: flagged `from pipes import quote` — nuance below.
A second catch: `pallets/click@b625654` (echo_via_pager regression fix) —
tautology correctly flagged the reconstructed buggy change.

**3. The deps flag is an era artifact worth reporting.** `pipes` was stdlib in
2020 and removed in Python 3.13, so today's verifier correctly says "not in
stdlib, not on PyPI" — right answer today, anachronistic for the commit's time.
Replay evaluation of environment-sensitive verifiers must be era-aware.

**4. Environment decay bounds historical replay (the main harness lesson).**
- 33/55 sample venvs built successfully (editable install); 22 failed
  (setup.py of that era incompatible with modern setuptools/Python).
- Even among built envs, historical test suites almost never run on
  Python 3.14: mutation could fully execute on 1/55 samples (52 ERROR:
  suite red at HEAD), tautology on 5/55.
- Conclusion for Phase 3: detection-rate claims for test-executing verifiers
  require era-matched interpreters (pyenv 2.7/3.6–3.9 per sample date) —
  the same environment problem BugsInPy/SWE-bench solve with pinned images.
  Static verifiers (deps; future: contract, review) don't have this problem —
  they ran on 55/55.

## Numbers

| verifier  | ran | flagged | skip | error |
|-----------|----:|--------:|-----:|------:|
| deps      | 55  | 1       | 0    | 0     |
| mutation  | 1   | 1       | 2    | 52    |
| tautology | 5   | 2       | 25*  | 25    |

\* all 25 skips = "diff adds/changes no test files" — see headline 1.

## Run 2 — cross-model review arm (2026-08-01)

Reviewer: Gemini (`gemini-flash-latest` on 24 bad samples, `gemini-flash-lite-latest`
on 31 bad + all 39 control samples; free-tier daily quotas forced the split, and
`reviewer_model` is recorded per sample). Adversarial review prompt, JSON findings,
warn/block severities. Raw data: `review.json` (bad arm), `review-control.json`
(control arm), `review-flash-partial.json` (flash-only snapshot).

**Design:** 55 known-bad diffs (run 1 corpus) vs. 39 presumed-good control commits
(same repos, merged ≥ 1 year ago, never reverted, not fixes/reverts themselves,
same size/language filters).

| arm | flagged | rate |
|---|---|---|
| known-bad (n=55) | 44 | **80% sensitivity** |
| presumed-good control (n=39) | 21 | **54% false-positive rate** |

Model-consistent subsets agree: flash flagged 19/24 bad (79%); lite flagged 25/31
bad (81%) and 21/39 good (54%) — so the lite-vs-lite comparison is 81% TPR at 54%
FPR (Youden's J ≈ 0.27). Counting only `block`-severity findings barely changes
the picture (46% of good commits still blocked).

**Reading:** an LLM prompted to attack a diff attacks almost everything. The
discrimination signal is real (80% vs 54%, ~27 points) but far too weak to gate
on alone — deployed at 54% FPR, developers would disable it within a week. This
is the first controlled sensitivity/specificity measurement we know of for the
"adversarial cross-model review" pattern that several commercial review agents
sell, and it quantifies why Vouch's design composes execution-grounded verifiers
(mutation, tautology) with review instead of trusting review alone.

**Caveats:** single reviewer family so far (GPT joins when the OpenAI account is
funded — the cross-family comparison is the point of the experiment design);
"presumed good" labels are survival-based (aged ≥ 1 year unreverted), which is
noisy — some flagged controls may contain genuine latent defects; finding-level
validity (does the review text describe a *real* defect in the reverted change?)
is not yet judged, only diff-level flagging.

## Implications for the evaluation design

1. Add an era-matched environment builder (pyenv + dated pip constraints) —
   unlocks mutation/tautology on the historical corpus.
2. Add a "test-evidence" micro-verifier (blocks diffs whose changed impl lines
   have no executing test) — it is the cheap signal headline 1 shows would
   have flagged 45% of real bad merges, and it needs no era matching when run
   at merge time.
3. The AI-authored arm (models re-implement the same changes today, gated in
   today's environment) sidesteps era decay entirely — strengthen its role in
   the paper design.
