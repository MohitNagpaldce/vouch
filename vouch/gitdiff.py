from __future__ import annotations

import re
from pathlib import Path

from .models import DiffContext, FileDiff
from .util import run_git

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def load_diff(repo: Path, base_ref: str, head_ref: str = "HEAD") -> DiffContext:
    merge_base = run_git(repo, "merge-base", base_ref, head_ref).strip()
    raw = run_git(repo, "diff", "-U0", "--no-color", merge_base, head_ref)
    new_files = set(
        run_git(
            repo, "diff", "--name-only", "--diff-filter=A", merge_base, head_ref
        ).splitlines()
    )

    files: list[FileDiff] = []
    current: FileDiff | None = None
    new_line_no = 0

    for line in raw.splitlines():
        if line.startswith("+++ "):
            path = line[4:]
            if path.startswith("b/"):
                path = path[2:]
            if path == "/dev/null":
                current = None
                continue
            current = FileDiff(path=path, is_new=path in new_files)
            files.append(current)
        elif line.startswith("@@") and current is not None:
            m = _HUNK_RE.match(line)
            if m:
                start = int(m.group(1))
                count = int(m.group(2)) if m.group(2) is not None else 1
                new_line_no = start
                current.changed_lines.update(range(start, start + count))
        elif line.startswith("+") and not line.startswith("+++") and current is not None:
            current.added_text.append((new_line_no, line[1:]))
            new_line_no += 1

    return DiffContext(
        base_ref=base_ref,
        head_ref=head_ref,
        merge_base=merge_base,
        files=files,
        raw=raw,
    )
