import subprocess
from pathlib import Path

import pytest

from vouch.gitdiff import load_diff
from vouch.provenance import detect_provenance


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@t.t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "mod.py").write_text("def f():\n    return 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "init")
    _git(tmp_path, "checkout", "-b", "feature")
    (tmp_path / "mod.py").write_text("def f():\n    return 2\n")
    (tmp_path / "test_mod.py").write_text("from mod import f\n\ndef test_f():\n    assert f() == 2\n")
    _git(tmp_path, "add", ".")
    _git(
        tmp_path, "commit", "-m",
        "change\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>",
    )
    return tmp_path


def test_diff_parses_changed_lines(repo: Path):
    diff = load_diff(repo, "main")
    by_path = {f.path: f for f in diff.files}
    assert by_path["mod.py"].changed_lines == {2}
    assert by_path["test_mod.py"].is_new
    assert by_path["test_mod.py"].is_test
    assert not by_path["mod.py"].is_test


def test_impl_and_test_split(repo: Path):
    diff = load_diff(repo, "main")
    assert [f.path for f in diff.python_impl_files] == ["mod.py"]
    assert [f.path for f in diff.python_test_files] == ["test_mod.py"]


def test_provenance_detects_claude_trailer(repo: Path):
    diff = load_diff(repo, "main")
    prov = detect_provenance(repo, diff.merge_base)
    assert prov.is_ai
    assert prov.models == ["anthropic/claude"]
