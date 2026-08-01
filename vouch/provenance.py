from __future__ import annotations

import re
from pathlib import Path

from .models import Provenance
from .util import run_git

# Known AI author/co-author markers → canonical model family
_AI_MARKERS: dict[str, str] = {
    "claude": "anthropic/claude",
    "anthropic": "anthropic/claude",
    "copilot": "openai/gpt",  # Copilot is GPT-family by default
    "codex": "openai/gpt",
    "gpt": "openai/gpt",
    "openai": "openai/gpt",
    "gemini": "google/gemini",
    "jules": "google/gemini",
    "cursor": "unknown/cursor",
    "aider": "unknown/aider",
    "devin": "unknown/devin",
    "windsurf": "unknown/windsurf",
}

_TRAILER_RE = re.compile(
    r"^\s*(?:co-authored-by|generated-by|assisted-by)\s*:\s*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)


def detect_provenance(repo: Path, merge_base: str, head_ref: str = "HEAD") -> Provenance:
    prov = Provenance()
    log = run_git(repo, "log", f"{merge_base}..{head_ref}", "--format=%an <%ae>%n%B%x00")
    for entry in log.split("\x00"):
        entry = entry.strip()
        if not entry:
            continue
        # author line + trailers both checked against markers
        candidates = [entry.splitlines()[0]] + _TRAILER_RE.findall(entry)
        for cand in candidates:
            low = cand.lower()
            for marker, family in _AI_MARKERS.items():
                if marker in low:
                    prov.is_ai = True
                    if family not in prov.models:
                        prov.models.append(family)
                    evidence = f"commit marker: {cand.strip()!r}"
                    if evidence not in prov.evidence:
                        prov.evidence.append(evidence)
    return prov
