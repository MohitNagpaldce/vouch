# Vouch — Research & Build Plan

## Phase 0 — Positioning (1–2 weeks)
- Related-work sweep: TestGen-LLM acceptance filters (Meta), SAFuzz, metamorphic
  prompt testing, PBT-for-LLM-code (FSE '25), in-toto/SLSA attestations, PBOM
  vendors. Claim to defend: *no existing framework unifies AI-specific verifiers
  behind a policy gate with portable attestations.*
- Decide scope for v1: **Python only** (mutmut/Hypothesis ecosystem mature),
  GitHub Action + Claude Code hook as the two integration points.

## Phase 1 — Core framework (3–4 weeks)
- Verifier plugin interface: `verify(diff, repo_ctx, policy) -> Findings`.
- v1 verifiers, in priority order:
  1. **Diff-scoped mutation testing** — mutate only lines touched by the diff plus
     direct callees; run only the tests that cover them (coverage map). Target:
     < 5 min on a typical PR. NOTE: diff-scoping itself is prior art (Google's
     code-review mutation testing, ICSE-SEIP 2018; Pitest/Stryker incremental
     modes) — cite it, don't claim it. The contribution is using mutation adequacy
     as an automated *gate for AI-authored code* (self-verification threat model),
     open and agent-native, plus the measured false-accept rate of
     build/pass/coverage acceptance filters vs. mutation adequacy.
  2. **Tautology probe** — run the diff's tests against (a) the unmodified base
     branch and (b) k mutated implementations; tests that pass everywhere are flagged.
  3. **Dependency reality check** — new imports → PyPI existence, age, download
     count, edit-distance to popular packages.
  4. **Cross-model review** — pluggable model API, structured findings schema,
     policy-enforced author≠reviewer.
- `vouch.toml` policy engine with risk tiers (path-based + diff-size-based).
- Provenance detection: Co-Authored-By trailers, agent env markers, explicit flag.

## Phase 2 — VBOM attestation (1–2 weeks)
- JSON schema; sign with sigstore/cosign; emit as in-toto predicate so existing
  supply-chain tooling can consume it. Write the spec as a standalone doc — this
  is the "standard" artifact.
- Badge endpoint (static JSON → shields.io) for the README score.

## Phase 3 — Evaluation (4–6 weeks)
- **Seeded-bug corpus:** mine merged-then-reverted PRs and regression-fix commits
  from popular Python repos; reverse-apply fixes to create realistic buggy diffs
  with ground truth. Also generate AI-authored diffs (3–4 models) for the same
  tasks. Target ≥ 200 diffs.
- **Baselines:** coverage-threshold gate, SAST (Semgrep/Bandit), plain generated
  test suite, single-model self-review.
- **Metrics:** per-verifier and combined detection rate, false-block rate,
  wall-clock overhead, mutation-scoping speedup vs whole-repo mutation.
- **Ablation:** which verifiers carry the weight; author≠reviewer effect size
  (this doubles as the correlated-blindness result — B2 folded in).

## Phase 4 — Paper + launch (3–4 weeks)
- Research paper → FSE/ISSTA; demo paper → ICSE/ASE demo track; arXiv immediately.
- OSS launch: polished README, GitHub Action in the marketplace, Claude Code hook
  snippet, 10-minute quickstart. Practitioner blog post + submit to newsletters
  (Pragmatic Engineer, TLDR, Changelog).
- Artifact-evaluation badge at the venue (Available/Reusable) — extra evidence.

## Risks
- **Mutation testing too slow even scoped** → fall back to fixed mutant budget per
  diff (sample), still novel as "adequacy sampling."
- **Adoption is a long game** → the demo-track paper + registered-report-style
  evaluation de-risk the publication outcome independent of adoption.
- **A vendor ships something similar first** → the VBOM/attestation angle and the
  peer-reviewed evaluation are the defensible parts; tools without evaluations
  can't publish.

## Success criteria (12 months)
- 1 research-track acceptance + 1 demo-track acceptance.
- 500+ GitHub stars or 100+ Action installs.
- ≥ 2 external projects or papers using Vouch or the VBOM format.
