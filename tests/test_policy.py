from pathlib import Path

import pytest

from vouch.policy import load_policy


@pytest.fixture
def default_policy(tmp_path: Path):
    return load_policy(tmp_path)  # no vouch.toml → embedded default


def test_default_policy_has_tiers(default_policy):
    names = [t.name for t in default_policy.tiers]
    assert names == ["critical", "default"]


def test_critical_paths_route_to_critical_tier(default_policy):
    tier = default_policy.tier_for(["src/auth_service.py", "docs/readme.md"])
    assert tier.name == "critical"
    assert "review" in tier.verifiers


def test_ordinary_paths_route_to_default_tier(default_policy):
    tier = default_policy.tier_for(["src/utils.py"])
    assert tier.name == "default"
    assert tier.config["min_mutation_score"] == 0.5


def test_custom_policy_file(tmp_path: Path):
    (tmp_path / "vouch.toml").write_text(
        """
fail_on = "warn"
[[tier]]
name = "all"
paths = ["**"]
verifiers = ["deps"]
min_mutation_score = 0.9
"""
    )
    policy = load_policy(tmp_path)
    assert policy.fail_on == "warn"
    assert policy.tier_for(["x.py"]).config["min_mutation_score"] == 0.9
