# Vouch evaluation corpus

Ground-truth buggy changes mined from real git history, for evaluating
verification gates. Two sample kinds:

- **merged_then_reverted** — a commit that shipped and was later reverted with
  "This reverts commit …". The strongest available label that a change was
  wrong: real maintainers merged it, then undid it.
- **regression_fix** — a commit whose subject declares it fixes a regression;
  reverse-applying it reconstructs the buggy state it removed.

Filters: touches ≥ 1 non-test `.py` file, diff ≤ 800 lines.

## Reproduce

```bash
python eval/mine_reverts.py \
  --repos psf/requests pallets/click pallets/flask psf/black \
          encode/httpx pydantic/pydantic fastapi/fastapi Textualize/rich \
  --out eval/corpus --limit 40 --workdir eval/.clones
```

Current collection: **55 samples across 8 repos** (see `corpus/stats.json`).
`eval/corpus/` and `eval/.clones/` are gitignored; the corpus is fully
regenerable from the script and pinned upstream history.

## Planned next steps (Phase 3 of the research plan)

1. Scale mining to 30+ repos → target ≥ 200 samples.
2. Replay harness: for each sample, apply the buggy diff on a branch at its
   parent commit and run `vouch check` — measuring which verifiers catch it.
3. Baselines on the same corpus: coverage-threshold gate, Semgrep/Bandit,
   single-model self-review.
4. AI-authored arm: have 3–4 model families implement the same changes from
   the PR/issue description; run the full verifier matrix (requires API keys
   for at least Anthropic, OpenAI, Google + one local open-weight model).
