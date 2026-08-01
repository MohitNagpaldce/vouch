# Related Work — Novelty Analysis (Phase 0)

*Last updated: 2026-07-31. Question: is a policy gate combining mutation adequacy,
tautology probes, cross-model review, dependency checks, contract conformance, and
property probes — with signed verification attestations — for AI-authored code new?*

**Verdict: every component exists individually; no tool or paper combines them as a
gate for AI-authored code, none emits verification attestations, and none has a
peer-reviewed evaluation. The composition, the attestation format, and the
comparative evaluation are the defensible contributions.**

## Nearest neighbors, and the gap each leaves

### Tools / industrial systems

| System | What it does | What it lacks (vs. Vouch) |
|---|---|---|
| **Open Code Review** (GitHub Action, `@opencodereview/cli`) | Closest tool. Self-described "first open-source CI/CD quality gate built specifically for AI-generated code": hallucinated-import checks (npm/PyPI/Maven/Go), stale-API detection, security anti-patterns, LLM deep scan | No mutation testing, no tautology detection, no cross-model policy, no contract conformance, no property testing, no attestations, no paper. 32 stars, BSL-1.1 license (not OSI-open until 2030) |
| **Meta ACH** (eng. blog 2025; FSE'25 keynote "Harden and Catch") | Deployed: LLM generates domain-specific mutants + tests that kill them, for compliance/privacy hardening; 73% test acceptance | Inverse direction: uses mutation to *generate* tests for human code; does not gate or evaluate AI-authored code; no adequacy scoring of existing AI tests; internal-only; no attestation |
| **Google mutation testing in code review** (ICSE-SEIP 2018+) | Diff-scoped mutants surfaced as review findings at scale | Advisory to human reviewers on human code; not a gate, not AI-specific, internal-only. Establishes diff-scoping as prior art — cite, don't claim |
| **Meta TestGen-LLM** (FSE-Companion 2024) | Accepts generated tests via build/pass/coverage-improvement filters | The filter Vouch's evaluation audits; no mutation adequacy, no gating of code |
| **Mutahunter** (OSS) | LLM-generated semantic mutants, language-agnostic | Mutation engine only; no gate, no policy, no AI-code focus, no evaluation paper |
| **Pitest/Stryker incremental** | Diff-aware mutation in CI | Generic engines; prior art for scoping |
| **CodeRabbit / Greptile / review agents** | LLM PR review as product | Single-layer (review only); no adequacy measurement, no independence policy (author model may equal reviewer), no attestation, anecdotal efficacy |

### Academic

| Work | What it does | Gap |
|---|---|---|
| **Clover** (Stanford, AI Verification 2024) | Closed-loop consistency checking of code/docstring/formal-annotation triples in Dafny; zero false positives on CloverBench | Formal-verification setting, toy programs, requires Dafny; not applicable to mainstream PR gating |
| **PBT for LLM code** (FSE 2025, "From Prompts to Properties") | Property-based testing improves LLM codegen validation | One verifier of six; no gate/framework/attestation |
| **Metamorphic prompt testing** (arXiv 2406.06864) | Validates LLM output via prompt metamorphism | Single technique; same |
| **MuTAP and mutation-guided test-gen line** | Mutation feedback improves LLM test generation | Generation-side, not adequacy gating |
| **SAFuzz** (arXiv 2602) | Semantic-guided fuzzing for LLM code | Single technique |
| **AI-code detection datasets** (Droid, AIGCodeSet, MultiAIGCD) | Detect *whether* code is AI-written | Provenance input to Vouch, orthogonal |
| **AIBoMGen** (arXiv 2601) | Signed CycloneDX BOM + in-toto attestation for *model training* | Closest attestation work; covers training pipelines, not verification evidence for AI-authored source diffs. VBOM gap confirmed |
| **SLSA / in-toto** | Build provenance attestation ecosystem | Records who/how built — not what verification the code survived. VBOM slots in as a new predicate type |

## Claim wording for the paper

Safe to claim:
1. First **open framework** composing test-adequacy, independence-enforced review,
   and ecosystem checks behind a **risk-tiered policy gate for AI-authored diffs**.
2. First **attestation format for verification evidence** of AI-authored code
   (in-toto predicate; complements SLSA build provenance and AIBOM training BOMs).
3. First **controlled comparison** of these verifier classes against deployed
   acceptance practices (coverage filters, SAST, self-review) on a common
   real-bug corpus, with per-verifier ablation.

Do NOT claim: mutation testing novelty, diff-scoping novelty, LLM-mutant novelty,
first AI-code quality gate (Open Code Review predates; cite it), first
cross-model review idea (practitioner literature predates).

## Watch list (re-check before submission)
- Open Code Review adding mutation/attestation features.
- Qodo, CodeIntegrity, Checkmarx/Snyk AI-code products shipping combined gates.
- FSE/ISSTA 2026 proceedings for gate-style frameworks.
