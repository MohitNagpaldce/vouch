from __future__ import annotations

import fnmatch
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_POLICY = """\
# Vouch policy. First matching tier (top to bottom) wins per file; the diff's
# tier is the highest-listed tier any changed file matches.
fail_on = "block"   # exit non-zero on: "block" | "warn"

[[tier]]
name = "critical"
paths = ["**/auth*", "**/*payment*", "**/*billing*", "**/security*", "**/infra/**", "**/migrations/**"]
verifiers = ["deps", "mutation", "tautology", "review"]
min_mutation_score = 0.7

[[tier]]
name = "default"
paths = ["**"]
verifiers = ["deps", "mutation", "tautology"]
min_mutation_score = 0.5
"""


@dataclass
class Tier:
    name: str
    paths: list[str]
    verifiers: list[str]
    config: dict = field(default_factory=dict)

    def matches(self, path: str) -> bool:
        return any(fnmatch.fnmatch(path, pat) for pat in self.paths)


@dataclass
class Policy:
    tiers: list[Tier]
    fail_on: str = "block"

    def tier_for(self, paths: list[str]) -> Tier:
        best: Tier | None = None
        best_idx = len(self.tiers)
        for path in paths:
            for idx, tier in enumerate(self.tiers):
                if tier.matches(path):
                    if idx < best_idx:
                        best, best_idx = tier, idx
                    break
        return best if best is not None else self.tiers[-1]


def load_policy(repo: Path) -> Policy:
    policy_file = repo / "vouch.toml"
    text = policy_file.read_text() if policy_file.exists() else DEFAULT_POLICY
    data = tomllib.loads(text)
    tiers = []
    for t in data.get("tier", []):
        known = {"name", "paths", "verifiers"}
        tiers.append(
            Tier(
                name=t["name"],
                paths=t.get("paths", ["**"]),
                verifiers=t.get("verifiers", []),
                config={k: v for k, v in t.items() if k not in known},
            )
        )
    if not tiers:
        raise ValueError("vouch.toml defines no [[tier]] entries")
    return Policy(tiers=tiers, fail_on=data.get("fail_on", "block"))
