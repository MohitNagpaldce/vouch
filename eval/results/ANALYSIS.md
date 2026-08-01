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

## Run 3 — GPT arm, cross-family ensemble, SAST baseline (2026-08-01)

Raw data: `review-gpt.json`, `review-gpt-control.json` (GPT-5.1, zero errors,
paid tier), `sast.json`, `sast-control.json` (Bandit 1.9.4 on changed lines).

| detector | sensitivity (n=55 bad) | FPR (n=39 good) | Youden J |
|---|---|---|---|
| Bandit (SAST, changed lines) | 2.4% (1/42 ran) | 8.8% (3/34 ran) | ~0 |
| GPT-5.1 adversarial review | 51% (28/55) | 31% (12/39) | 0.20 |
| Gemini flash adversarial review | 80% (44/55) | 54% (21/39) | 0.27 |
| **Union (either family flags)** | **89% (49/55)** | **54% (21/39)** | **0.35** |
| Intersection (both must flag) | 42% (23/55) | 31% (12/39) | 0.11 |

**Cross-family structure — the day's most useful finding.** The two families'
*false positives are nested*: GPT's 12 flagged controls are a subset of
Gemini's 21, so the union's FPR equals Gemini's alone. Their *true positives
are complementary*: on the bad arm, Gemini-only caught 21 samples and GPT-only
caught 5 (agreement on only 23). Consequences:

1. **Union dominates the best single reviewer**: +9 points sensitivity (89% vs
   80%) at identical FPR. Cross-family review composition is free sensitivity.
2. **Requiring agreement does NOT fix false positives**: intersection FPR (31%)
   is no better than conservative-GPT alone, because the families' FP sets
   overlap heavily — both attack the same innocuous-but-unusual good diffs.
   "Two reviewers must agree" is NOT the fix vendors might assume.
3. Detection blindness is family-specific (weakly correlated errors on bad
   diffs); false-alarm behavior is shared (strongly correlated on good diffs) —
   likely an artifact of the shared adversarial prompt framing. Calibration
   work should target the prompt, not the ensemble.

**SAST is the mirror image of LLM review.** Bandit flagged 1 real regression
out of 42 runnable (a `subprocess`-adjacent change) at 8.8% FPR. Precise,
nearly blind to logic regressions — exactly the heterogeneity that motivates
composing verifier classes rather than picking one.

## Run 4 — test-evidence baseline: run 1's headline dies against its control (2026-08-01)

The naive gate "diff must touch a test file": flags 25/55 bad (45% sensitivity)
but also 25/39 good (64% FPR) — worse than chance (J ≈ −0.19). Merging without
test changes is just how these projects work, for good and bad changes alike.
Run 1's "a cheap gate would have caught 45%" framing is hereby retracted; the
paper now presents this as a worked example of why every gate signal needs a
control arm. The discriminative form of the signal is execution-level (no test
executes the changed lines — cf. the shlex.quote sample: test file touched,
11/11 changed-line mutants uncovered), i.e., diff-scoped mutation coverage at
merge time.

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
