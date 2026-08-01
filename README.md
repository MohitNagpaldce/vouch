# Vouch — a verification gate for AI-generated code

*Working name; alternatives: `attest`, `warrant`, `vet`.*

**One-liner:** Vouch is a pluggable framework that sits between an AI coding agent
and merge. It runs a battery of AI-specific verifiers over each AI-authored diff,
scores verification adequacy, enforces a risk-tiered policy, and emits a signed,
machine-readable **attestation** of exactly what checks the code passed.

**Thesis of the paper:** unit/integration tests and coverage are the wrong adequacy
signal for AI-generated code (coverage is gameable, tests are often written by the
same model that wrote the code). AI-authored diffs need a *dedicated verification
layer* with checks targeting AI-specific failure modes — and the result must be a
portable attestation, not a green checkmark.

## Why this can become an adopted standard

1. **Drop-in adoption channels.** Ships as a GitHub Action, a pre-commit hook, and
   a coding-agent hook (Claude Code hooks / MCP server) — so it runs *inside* the
   agent loop, before a human ever sees the diff. Agent-config ecosystems spread
   virally (people share their hooks/actions).
2. **A standard artifact, not just a tool.** The output is a **Verification Bill of
   Materials (VBOM)**: an in-toto/SLSA-style attestation recording provenance
   (which model authored the diff) plus which verifiers ran and their results.
   This plugs into the existing supply-chain-attestation ecosystem instead of
   inventing a parallel one — the realistic path for an independent researcher's
   format to become a standard.
3. **A number people can put in a README.** A verification-adequacy score + badge,
   like coverage badges — the growth loop that made Codecov/coverage ubiquitous.

## The verifiers (pluggable)

| Verifier | AI failure mode it targets |
|---|---|
| Diff-scoped mutation testing | Tautological/weak tests written by the authoring model; coverage-gaming (the core technical novelty: mutation testing made CI-fast by scoping mutants to the diff) |
| Tautology probe | Generated tests that pass on deliberately broken implementations |
| Cross-model adversarial review | Correlated blindness when author-model == reviewer-model; structured findings, independent model required by policy |
| Dependency reality check | Hallucinated / squattable packages (registry existence + age + typo-distance) |
| Contract conformance | Misread API schemas — validate against real OpenAPI/protobuf specs, not mocks |
| Property probes | Overfitting to examples — auto-derived invariants (round-trips, idempotence, metamorphic relations) run via Hypothesis/fast-check |

Policy lives in `vouch.toml`: risk tiers (e.g. touches auth/payments/infra → all
verifiers + human gate; docs/tests-only → fast path), required independence
(reviewer model ≠ author model), minimum mutation score per tier.

## Paper plan

- **Contribution 1:** the framework + the VBOM attestation format.
- **Contribution 2:** diff-scoped mutation testing (algorithm + overhead evaluation
  showing it is CI-viable where whole-repo mutation is not).
- **Contribution 3:** evaluation — seeded-bug corpus built from real reverted/
  regression-fix PRs; detection rate of Vouch vs. baselines (coverage gate, SAST,
  plain generated tests, single-model review); ablation per verifier; runtime cost.
- **Venues:** FSE or ISSTA (research track) + tool-demo track paper (ICSE/ASE demo
  tracks are lower-bar and give a second peer-reviewed publication for the same
  artifact); extended version to EMSE or TOSEM.

## Status

Early research phase. Related-work analysis in [docs/related-work.md](docs/related-work.md).
