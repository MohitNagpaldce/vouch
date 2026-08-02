# Vouch: A Verification Gate for AI-Generated Code, with Portable Evidence Attestations

**Mohit Nagpal**
Independent Researcher
mht.nagpal@gmail.com

*Draft v0.1 — 2026-08-01. Sections marked ⏳ await experiments in progress.*

---

## Abstract

AI coding assistants now author a substantial fraction of merged code, and the
same model that writes the implementation typically also writes the tests that
"verify" it. Industrial acceptance pipelines gate this code on the signals used
for human code — the tests build, pass, and increase coverage — signals that are
structurally weak when author and verifier share failure modes. We present
**Vouch**, an open-source verification gate purpose-built for AI-authored
changes. Vouch composes six verifier classes targeting AI-specific failure
modes — diff-scoped mutation adequacy, tautological-test probes, cross-model
adversarial review with enforced author/reviewer independence, dependency
reality checks, contract conformance, and property probes — behind a
risk-tiered policy, and emits a **Verification Bill of Materials (VBOM)**: an
in-toto-style attestation recording which model authored a diff and which
verification evidence it survived. We evaluate the first four verifiers on a
mined corpus of 55 ground-truth bad changes (merged-then-reverted and
regression-introducing commits from eight major Python projects) and a
39-commit presumed-good control arm. Three findings stand out: (1) 45% of
known-bad changes shipped without touching a single test file — but so did 64%
of known-good ones, so the obvious cheap gate ("require test changes") does
not discriminate at all; the discriminative form of the signal is
execution-level — *no test executes the changed lines* — which is exactly what
diff-scoped mutation coverage measures, and our own initially-promising
headline failing its control arm is a working demonstration of why every gate
signal must be evaluated against one; (2) where the full gate was runnable it blocked
the bad change — in the strongest case, mutation testing found 11/11 injected
faults undetected because no test executed any changed line, and the tautology
probe proved the accompanying test passed *without* the change; (3) adversarial
LLM review, measured with a control arm across two model families for the
first time to our knowledge, discriminates weakly alone (Gemini: 80%
sensitivity at 54% false-positive rate; GPT-5.1: 51% at 31%) but exhibits a
striking cross-family structure — false positives are nested across families
while true positives are complementary — so the two-family union gains nine
points of sensitivity for free (89%) while requiring cross-family agreement
fails to reduce false alarms, informing both why execution-grounded verifiers
must anchor the gate and how review should be ensembled within it. Vouch is
available as a CLI, GitHub Action, and coding-agent hook.

**Keywords:** AI-generated code, mutation testing, test adequacy, code review
agents, software supply chain, attestation

---

## 1. Introduction

A growing share of production code is written by large language models —
sometimes autocompleted line by line, increasingly authored wholesale by coding
agents that also write the tests, run them, and open the pull request. The
review question for such a change is no longer only *"is this code correct?"*
but *"is the evidence that it is correct worth anything?"*

Today's de-facto industrial answer treats AI-authored code like human code with
extra volume: run the linters, require the tests to build and pass, ask that
coverage not decrease, and have a human (or, increasingly, another LLM) skim
the diff. Meta's TestGen-LLM [1], the most prominent published industrial
pipeline for LLM-written tests, accepts a generated test exactly when it
builds, passes reliably, and increases coverage. These signals share a flaw:
they can all be satisfied by a test suite that verifies nothing, and the model
that wrote the implementation has every opportunity to write exactly such a
suite — not adversarially, but because example-based tests generated from the
same context as the code inherit the code's blind spots. Coverage, in
particular, is satisfied by *executing* a line, not by *checking* it.

This paper asks what a verification gate designed specifically for AI-authored
changes should look like, builds one, and measures its verifier classes against
ground truth from real project history. Our claims:

1. **A design** (Section 3): six verifier classes, each targeting a documented
   AI-specific failure mode, composed behind a risk-tiered policy with an
   enforced author≠reviewer independence rule, running in CI, pre-commit, or
   inside the coding agent's own loop.
2. **A portable evidence format** (Section 4): the VBOM, an in-toto predicate
   recording provenance (which model authored the diff) and verification
   evidence (which verifiers ran, their metrics, their findings). Supply-chain
   attestation infrastructure records *how code was built* [8]; nothing today
   records *what verification AI-authored code survived*.
3. **Measurements against real ground truth** (Sections 5–6): a reproducible
   corpus of 55 merged-then-reverted and regression-introducing changes plus a
   39-commit control arm, on which we quantify (a) how often real bad changes
   ship with no test evidence at all, (b) end-to-end gate behavior where
   runnable, including environment-decay bounds we characterize honestly, and
   (c) the first controlled sensitivity/specificity measurement of the
   "adversarial cross-model review" pattern now sold by commercial review
   agents.

We do not claim novelty for any individual verifier idea. Mutation testing is
decades old and runs diff-scoped in Google's code review [2]; hallucinated-
dependency checking exists in at least one open-source tool [7]; property-based
testing for LLM code has an FSE paper [4]. The contribution is the composition
as a *gate* under a self-verification threat model, the attestation format, and
the controlled evaluation — none of which, per our review of the literature and
tooling landscape (Section 2), exists today.

## 2. Related Work

**Industrial acceptance of LLM-written tests.** TestGen-LLM at Meta [1] filters
generated tests through build/pass/coverage-improvement gates; 73% of surviving
recommendations were accepted by engineers. Meta's later ACH system [5] inverts
the direction we study: an LLM generates domain-specific *mutants* and then
tests that kill them, hardening code against future faults. Neither system
measures whether accepted tests are adequate in the mutation sense, and neither
gates AI-authored implementation code.

**Mutation testing in review.** Google runs mutation testing at scale inside
code review [2], surfacing surviving mutants on changed lines as advisory
review comments for human-authored code; Pitest and Stryker ship incremental
modes. We reuse the diff-scoping idea (citing it as prior art) but repurpose
mutation adequacy as a *blocking gate* under a policy, applied to AI-authored
diffs where the authoring model also wrote the tests.

**Verification of LLM-generated code.** Clover [3] checks consistency among
code, docstrings, and formal Dafny annotations — strong guarantees in a formal
setting, not applicable to mainstream PR gating. Property-based testing [4] and
semantic-guided fuzzing [6] validate LLM code with generated inputs; both are
single techniques that slot naturally into our verifier interface. Metamorphic
prompt testing [9] validates outputs by prompt perturbation, again as a
standalone technique.

**AI-code quality gates.** The closest tool is Open Code Review [7], an
open-source CI gate for AI-generated code offering hallucinated-import checks,
stale-API detection, and LLM review layers. It has no mutation testing, no
tautology probing, no reviewer-independence policy, no contract checking, no
attestation output, and no published evaluation. Commercial review agents
(CodeRabbit, Greptile, and others) productize LLM PR review; their efficacy
claims are anecdotal, and Section 6 provides what we believe is the first
controlled measurement of the pattern's false-positive behavior.

**Attestation.** SLSA provenance and in-toto attestations [8] record builder
identity, sources, and build parameters; AIBoMGen [10] extends BOM-style
attestation to model *training* pipelines. No existing predicate records
verification evidence for AI-authored source changes; the VBOM (Section 4)
fills exactly this slot, deliberately as an in-toto predicate so existing
supply-chain tooling can consume it.

## 3. Design

### 3.1 Threat model: self-verification

The defining risk of AI-authored changes is not malice but *correlated
blindness*: one model produces the implementation, the tests, and often the PR
description that a human skims. Green checkmarks then encode the model's
self-agreement rather than independent evidence. Vouch's design rule: every
verifier must derive its verdict from a source the authoring model does not
control — injected faults (mutation), the pre-change codebase (tautology
probe), a different model family (review), the package registry (dependency
check), the declared API contract (conformance), or generated inputs (property
probes).

### 3.2 Verifiers

**Diff-scoped mutation adequacy.** Vouch parses the diff, collects mutation
sites only on changed lines (comparison/arithmetic/boolean operator swaps,
constant perturbations, `not`-removal), and evaluates each mutant in a
disposable git worktree. A per-test coverage map built from the baseline run
(pytest-cov dynamic contexts) scopes each mutant's execution to only the tests
covering the mutated line; mutants on lines no test executes are reported as
*uncovered* and count as surviving. The policy sets a minimum mutation score
per risk tier. Implementation note with practical value: on Python ≥3.12,
coverage.py's default `sys.monitoring` core disables line events after first
hit, silently attributing each line to only the first test that ran it — which
corrupts per-test maps and, in our testing, flipped killable mutants to
survivors; forcing the C tracer (`COVERAGE_CORE=ctrace`) restores correct
attribution.

**Tautology probe.** A test added alongside an implementation change should
fail against the *pre-change* implementation. Vouch reverts the diff's
implementation files (not its tests) to the merge-base inside the disposable
worktree and re-runs the diff's tests: if they still pass, they do not verify
the change they accompany, and the gate blocks with a ground-truth observation
rather than a heuristic.

**Cross-model adversarial review.** A reviewer model, prompted to attack the
diff and respond with structured findings, with a policy-enforced independence
rule: the reviewing model family must differ from the authoring family
(provenance is detected from commit trailers — `Co-Authored-By: Claude/
Copilot/...` — and agent markers). Providers (Anthropic, OpenAI, Google) are
pluggable; on provider failure the verifier falls back across the independence-
preserving candidates first.

**Dependency reality check.** Imports added by the diff are resolved against
the registry: nonexistent packages block (hallucinated imports are also
squattable names — a supply-chain exposure, not just a bug); very new packages
and names within small edit distance of popular packages warn.

**Contract conformance and property probes** complete the design (validating
requests/responses against the declared OpenAPI/protobuf contract rather than
model-imagined mocks; deriving invariants — round-trips, idempotence,
metamorphic relations — executed via Hypothesis). Both are specified in the
architecture and are not yet implemented in v0.1; the evaluation below covers
the first four verifiers.

### 3.3 Policy and placement

A `vouch.toml` maps path patterns to risk tiers; each tier names its required
verifiers and thresholds (e.g., auth/payment/infra paths require all verifiers
and a 0.7 mutation score; ordinary code requires the execution-grounded three
and 0.5). Vouch runs as a CLI, a GitHub Action (uploading the VBOM as a
workflow artifact), a pre-commit hook, or a coding-agent hook — the last
placement meaning the agent's own loop gets independent verification *before*
a human ever sees the diff.

## 4. The Verification Bill of Materials

Every gate run emits a VBOM: an in-toto Statement whose subject is the diff
digest and whose predicate records the tool version, detected provenance
(authoring model families and the evidence for the attribution), the policy
tier applied, each verifier's verdict, metrics, findings, and runtime, and the
aggregate verdict. The format piggybacks on the in-toto/SLSA ecosystem [8] so
existing attestation stores, policy engines, and transparency tooling can
consume it without modification; it complements build provenance (how the
artifact was produced) and AI BOMs (how a model was trained) with a third
axis: *what verification the change survived*. v0.1 emits unsigned statements;
sigstore signing is planned. The full JSON schema ships in the repository.

## 5. Evaluation I: ground-truth corpus and gate replay

### 5.1 Corpus

We mine ground-truth bad changes from git history — two labels that require no
human judgment: **merged-then-reverted** commits (a later commit declares "This
reverts commit X"; maintainers shipped X and undid it) and **regression-fix**
commits (subject declares a regression fix; reverse-applying the fix
reconstructs the buggy state). Filters: touches ≥1 non-test Python file, diff
≤800 lines. From eight projects (requests, click, flask, black, httpx,
pydantic, fastapi, rich) the miner yields **55 samples** (38 reverted, 17
regression). The miner and corpus are reproducible from pinned upstream
history.

### 5.2 Replay harness

Each sample is replayed as if it were a fresh PR: a worktree at the buggy
commit (or a `git revert` reconstruction for regression fixes), a per-sample
virtualenv with the project installed editable, and a full `vouch check`
against the sample's base, with per-verifier verdicts extracted from the VBOM.
Environments that fail to build and suites red at HEAD are recorded as such —
runnability is data, not noise.

### 5.3 Results

**45% of known-bad changes shipped with no test changes (25/55) — a signal
that dies against its control.** Nearly half of the changes real maintainers
merged and later reverted touched no test file. The obvious inference — "a
gate requiring test changes would have flagged 45% of real bad merges for
free" — is wrong: **64% of the presumed-good control commits (25/39) also
shipped without test changes**, so in these projects the naive gate
discriminates worse than chance (J ≈ −0.19). Merging without test changes is
simply how these projects operate, for good and bad changes alike. Two
lessons. First, methodological: every candidate gate signal must be evaluated
against a control arm — this one looked like a headline until it met its
control (and Section 6's review measurements were designed with controls from
the start for the same reason). Second, substantive: the discriminative form
of "test evidence" is not *did the diff touch a test file* but *does any test
execute the changed implementation lines* — file-level presence is a poor
proxy (the `shlex.quote` sample below touched a test file yet had 11/11
changed-line mutants uncovered). That execution-level signal is exactly what
diff-scoped mutation coverage measures at merge time, in the merge-time
environment, where era decay is not a factor.

**Where the full gate ran, it blocked the bad change.**
`pallets/click@e798f64` ("Use shlex.quote for quoting shell arguments," merged
2020, later reverted) is the paradigm case — every verifier fired: mutation
found **11/11 mutants on changed lines uncovered** (the only accompanying test
was an import-graph check; no test executed any changed line); the tautology
probe showed that test **passing against the pre-change implementation**; the
dependency check flagged the `pipes` import (an era nuance: stdlib in 2020,
removed in Python 3.13 — the flag is correct today and anachronistic for the
commit's time, so era-awareness matters when replaying environment-sensitive
verifiers). A second full catch: the tautology probe correctly blocked the
reconstructed `echo_via_pager` regression (`click@b625654`).

**Environment decay bounds historical replay of execution-grounded verifiers.**
33/55 sample environments built; even then, decade-old test suites rarely run
under Python 3.14 — mutation executed fully on 1/55 samples, the tautology
probe on 5/55, while the static dependency check ran on 55/55. Detection-rate
claims for execution-grounded verifiers on *historical* corpora therefore
require era-matched interpreters (the environment problem BugsInPy and
SWE-bench solve with pinned images) — or an evaluation arm where models
re-implement the changes *today* (Section 7). We report this bound rather than
quietly evaluating only the runnable subset.

## 6. Evaluation II: adversarial review, with a control arm

The "have a second model attack the PR" pattern is now standard advice and a
product category, evaluated — until now, to our knowledge — without a control
arm. Sensitivity without specificity is meaningless for a reviewer prompted to
find problems: it might flag everything.

**Design.** The 55 known-bad diffs versus **39 presumed-good control commits**
from the same projects: merged ≥1 year ago, never reverted, not themselves
reverts/fixes, same size and language filters, deterministic stride sampling.
Reviewer: Gemini (`gemini-flash-latest` for 24 bad samples,
`gemini-flash-lite-latest` for the remainder and all controls; free-tier daily
quotas forced the split, and the reviewer model is recorded per sample in the
VBOM). One adversarial review per diff, structured JSON findings.

**Results.** Two reviewer families ran both arms (GPT-5.1; Gemini flash/
flash-lite, reviewer model recorded per sample), plus a Bandit SAST baseline
restricted to findings on changed lines:

| detector | sensitivity (bad, n=55) | FPR (good, n=39) | Youden J |
|---|---|---|---|
| Bandit (SAST, changed lines) | 2.4% (1/42 ran) | 8.8% (3/34 ran) | ≈0 |
| GPT-5.1 review | 51% (28/55) | 31% (12/39) | 0.20 |
| Gemini review | 80% (44/55) | 54% (21/39) | 0.27 |
| **union (either flags)** | **89% (49/55)** | **54% (21/39)** | **0.35** |
| intersection (both flag) | 42% (23/55) | 31% (12/39) | 0.11 |

![Figure 1: Review discrimination. The calibrated GPT-5.1 ROC (AUC 0.65) with
every adversarial-framing detector plotted as an operating point: both
adversarial arms sit essentially on the calibrated curve, the cross-family
union sits above it, and the intersection adds nothing over
conservative-GPT.](figures/roc.png)

Counting only block-severity findings barely moves the single-reviewer
numbers (46% of good commits still blocked by Gemini, which blocked, among
other innocuous changes, a shebang addition and a comment update).

**Reading.** An LLM prompted to attack a diff attacks much of everything; the
families differ only in operating point (GPT conservative, Gemini aggressive),
and neither discriminates well alone. The cross-family *structure* is the
useful result. The two families' false positives are nested — GPT's 12 flagged
controls are a subset of Gemini's 21 — while their true positives are
complementary (Gemini-only 21, GPT-only 5, agreement 23). Hence: (1) the
**union dominates the best single reviewer** — nine points more sensitivity at
identical FPR — so cross-family composition is free sensitivity; (2)
**requiring agreement does not fix false alarms** — intersection FPR equals
conservative-GPT alone, because both families attack the same
innocuous-but-unusual good diffs, plausibly an artifact of the shared
adversarial prompt framing. Detection blindness is family-specific; false-alarm
behavior is shared. Calibration should target the prompt; ensembling should
target the union. SAST is the mirror image of review — near-zero false alarms,
near-blind to real regressions — completing the heterogeneity argument: no
single detector class gates AI code; composition does, with execution-grounded
verifiers (mutation, tautology) anchoring the gate on ground truth.

### 6.1 Calibration and finding validity: perception without conviction

Re-running GPT-5.1 with a calibrated prompt ("0–100 likelihood this change
introduces a defect") instead of the adversarial framing yields the full
curve: **AUC 0.647**, with operating points from 69%/48% (threshold ≥20) to
27%/6% (≥40, best J ≈ 0.21). The adversarial framing's point (51%/31%,
J 0.20) sits on the same curve: **prompt framing selects the operating point
but adds no discrimination** — LLM review carries a fixed, modest signal on
this corpus, and no point on its curve gates alone.

Finding-level validity explains where that signal goes. On the 42 bad diffs
where the calibrated reviewer produced findings, an LLM judge rated **36 (86%)
as describing the actual defect** behind the revert or regression — review's
problem is not hallucinated criticism. But of those 36 correctly-perceived
defects, **22 (61%) were scored below the best-J gating threshold**: in the
starkest case the reviewer explicitly described a pydantic revert's defective
conditional logic in its findings, then rated the change 5/100. The binding
failure of LLM code review is **calibration, not detection**: the model
articulates the true defect and underweights it (Figure 2).

![Figure 2: Perception without conviction. Reviewer defect-likelihood scores
for control commits, bad diffs whose findings missed the actual defect, and
bad diffs whose findings identified it — 22 of 36 correctly-perceived defects
score below the best-J gating threshold.](figures/conviction.png) This has two design
consequences. Gate logic should weigh finding *content* — a concrete
behavioral-change finding on a critical path — rather than scalar risk alone,
since thresholding discards the model's own correct perceptions. And it
reframes the union result above: cross-family union works because it harvests
correct perceptions that each family individually underweights.

**Caveats.** Survival-based "good" labels are noisy; the validity judge shares
a family with the reviewer (self-agreement inflation risk) and ground truth is
subject-line-granular; the Gemini arm mixes two model sizes (recorded per
sample; size-consistent subsets agree within two points); the calibrated
control ran on 48 of the eventual 111 controls.

⏳ *Pending: full-corpus (300/111) rerun of the review arms; AI-authored
re-implementation arm; era-matched environments for the execution-grounded
verifiers.*

## 7. Evaluation III: the gate on genuinely AI-authored code

The corpora above are human-authored; the self-verification thesis deserves a
direct measurement. We distilled 30 corpus changes into standalone,
stdlib-only specs (via GPT-5.1) and had two model families — GPT-5.1 and
Gemini — each independently author the module *and its own pytest suite*, the
one-shot self-verification setting. Each AI-authored diff (with genuine
provenance trailers) then ran through the gate in a fresh repository in
today's environment, eliminating the era-decay confound entirely.

| | GPT-5.1 | Gemini |
|---|---|---|
| own tests fail on own implementation | **37%** (11/30) | **34%** (10/29) |
| clean gate pass | 10% | 14% |
| mutation score of runnable suites (mean / median) | 0.69 / 0.71 | 0.63 / 0.68 |
| suites below 0.5 mutation score | 3/19 | 4/19 |
| changed lines with no executing test (uncovered mutants) | 28 | 26 |
| tautology blocks | 0 | 1 |

Three observations. First, **over a third of one-shot AI-authored changes ship
with test suites that fail on their own implementation** — the crudest
self-verification failure, at nearly identical rates across families. (Agents
that iterate until green mask this failure specifically, but not the adequacy
failures below.) Second, among suites that run, **mutation adequacy is
mediocre and family-independent** — mean 0.63–0.69, one in five below 0.5,
plus dozens of changed lines no test executes: coverage theater, measured
directly on AI code. Third, only 10–14% of AI-authored diffs pass the gate
cleanly — meaning a Vouch-style gate returns concrete, actionable evidence
(surviving mutants, uncovered lines, red tests) on roughly nine of ten AI PRs
rather than a rubber stamp. Tautological tests were rare here (0–1), locating
the dominant AI testing failure in *adequacy*, not tautology.

Caveats: one-shot generation deliberately isolates the model's unaided testing
judgment (production agents iterate-and-repair); the standalone-module setting
removes cross-file complexity; spec distillation by a single family is a
shared upstream bias; n=30 tasks per family.

## 8. Limitations and threats to validity

**Equivalent mutants.** Mutation scores undercount test quality when injected
faults are semantically null; our own demo surfaced one (`>` → `>=` at a
clamping boundary, unkillable by any test). Tier thresholds below 1.0 absorb
some of this; equivalence detection (Meta uses an LLM detector [5]) is future
work.

**Historical-corpus external validity.** Old commits, old idioms, modern
interpreter — Section 5.3 characterizes the decay honestly. The clean
evaluation of execution-grounded verifiers is the AI-authored arm: 3–4 model
families re-implement each corpus change from its PR/issue description in
today's environment, then the full verifier matrix runs — this also enables
the author≠reviewer effect-size measurement that motivates the independence
policy. ⏳ *Pending: requires funded API access across families.*

**Single language.** v0.1 targets Python; the verifier interfaces are
language-agnostic, the mutation and coverage machinery is not yet.

**Provenance is heuristic.** Commit trailers and agent markers under-detect
(silent AI authorship) and can be forged; the VBOM records the *evidence* for
attribution, not a guarantee. Gates can run `--all-code` where provenance is
unreliable.

## 9. Conclusion

Build-pass-coverage acceptance — the current industrial standard — measures the
authoring model's self-agreement, not independent evidence. We built the gate
that measures the latter: six verifier classes anchored in sources the
authoring model does not control, composed by policy, attested portably. The
first controlled measurements are a study in why controls matter: the obvious
cheap signal (no test changes in the diff) describes 45% of real bad merges
*and* 64% of good ones, dying against its control arm; the execution-grounded
verifiers block real bad changes with ground-truth observations; and
the fashionable one — adversarial LLM review — discriminates weakly in every
family we measured, yet composes well: the cross-family union reaches 89%
sensitivity at no extra false-alarm cost, while cross-family *agreement* fails
to suppress false alarms because the families share them. Every detector class
fails differently; that heterogeneity is the argument for a gate that composes
them rather than trusting any one. Vouch and its corpus are open source; the
VBOM format is offered as a starting point for verification evidence as a
first-class supply-chain artifact.

## References

[1] N. Alshahwan et al. "Automated Unit Test Improvement using Large Language
Models at Meta." FSE Companion 2024. arXiv:2402.09171.
[2] G. Petrović, M. Ivanković. "State of Mutation Testing at Google."
ICSE-SEIP 2018 (and follow-ups, ICSE-SEIP 2021).
[3] C. Sun, Y. Sheng, O. Padon, C. Barrett. "Clover: Closed-Loop Verifiable
Code Generation." AI Verification (SAIV) 2024. arXiv:2310.17807.
[4] "From Prompts to Properties: Rethinking LLM Code Generation with
Property-Based Testing." FSE 2025.
[5] Meta Engineering. "LLMs are the key to mutation testing and better
compliance" (ACH). engineering.fb.com, 2025; FSE 2025 keynote "Harden and
Catch."
[6] "SAFuzz: Semantic-Guided Adaptive Fuzzing for LLM-Generated Code."
arXiv:2602.11209.
[7] Open Code Review. github.com/marketplace/actions/open-code-review.
[8] in-toto attestations & SLSA provenance. in-toto.io, slsa.dev.
[9] "Validating LLM-Generated Programs with Metamorphic Prompt Testing."
arXiv:2406.06864.
[10] "AIBoMGen: Generating an AI Bill of Materials for Secure, Transparent,
and Compliant Model Training." arXiv:2601.05703.
