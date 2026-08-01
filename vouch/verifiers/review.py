from __future__ import annotations

import json
import os
import re
import urllib.request

from ..models import Finding, RunContext, Severity, Verdict, VerifierResult
from .base import Verifier, register

_SYSTEM = """You are an adversarial code reviewer in a CI gate for AI-generated code.
Attack the diff: hunt for logic bugs, silent failure paths, missing error handling,
misuse of APIs, security issues, and edge cases the author's tests do not cover.
Report ONLY genuine defects — no style nits. Respond with a JSON array (possibly
empty), each item: {"file": str, "line": int|null, "severity": "warn"|"block",
"message": str}. Respond with the JSON array only."""

_MAX_DIFF_CHARS = 60_000


class Provider:
    family: str = ""

    def available(self) -> bool: ...
    def review(self, diff_text: str) -> str: ...


class AnthropicProvider(Provider):
    family = "anthropic/claude"

    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("VOUCH_ANTHROPIC_MODEL", "claude-sonnet-5")
        self.key = os.environ.get("ANTHROPIC_API_KEY", "")

    def available(self) -> bool:
        return bool(self.key)

    def review(self, diff_text: str) -> str:
        body = json.dumps(
            {
                "model": self.model,
                "max_tokens": 2048,
                "system": _SYSTEM,
                "messages": [{"role": "user", "content": f"Review this diff:\n\n{diff_text}"}],
            }
        ).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            headers={
                "x-api-key": self.key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        return "".join(b.get("text", "") for b in data.get("content", []))


class OpenAIProvider(Provider):
    family = "openai/gpt"

    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("VOUCH_OPENAI_MODEL", "gpt-5.1")
        self.key = os.environ.get("OPENAI_API_KEY", "")

    def available(self) -> bool:
        return bool(self.key)

    def review(self, diff_text: str) -> str:
        body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": f"Review this diff:\n\n{diff_text}"},
                ],
            }
        ).encode()
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.key}",
                "content-type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"]


class GeminiProvider(Provider):
    family = "google/gemini"

    def __init__(self, model: str | None = None):
        # flash has free-tier quota for new users; pro requires paid billing
        self.model = model or os.environ.get("VOUCH_GEMINI_MODEL", "gemini-flash-latest")
        self.key = os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")

    def available(self) -> bool:
        return bool(self.key)

    def review(self, diff_text: str) -> str:
        body = json.dumps(
            {
                "system_instruction": {"parts": [{"text": _SYSTEM}]},
                "contents": [
                    {"role": "user", "parts": [{"text": f"Review this diff:\n\n{diff_text}"}]}
                ],
            }
        ).encode()
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent"
        )
        req = urllib.request.Request(
            url,
            data=body,
            headers={"x-goog-api-key": self.key, "content-type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        parts = data["candidates"][0]["content"].get("parts", [])
        return "".join(p.get("text", "") for p in parts)


PROVIDERS: list[Provider] = [AnthropicProvider(), OpenAIProvider(), GeminiProvider()]


def _parse_findings(text: str) -> list[dict]:
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return []
    try:
        items = json.loads(m.group(0))
        return [i for i in items if isinstance(i, dict) and i.get("message")]
    except json.JSONDecodeError:
        return []


@register
class ReviewVerifier(Verifier):
    """Cross-model adversarial review. Policy: the reviewing model family must
    differ from the authoring model family (correlated-blindness defense)."""

    name = "review"

    def run(self, ctx: RunContext) -> VerifierResult:
        result = VerifierResult(verifier=self.name, verdict=Verdict.PASS)
        available = [p for p in PROVIDERS if p.available()]
        if not available:
            result.verdict = Verdict.SKIP
            result.note = "no review provider configured (set ANTHROPIC_API_KEY or OPENAI_API_KEY)"
            return result

        author_families = set(ctx.provenance.models)
        independent = [p for p in available if p.family not in author_families]
        same_family = [p for p in available if p.family in author_families]
        if not independent:
            result.findings.append(
                Finding(
                    verifier=self.name,
                    severity=Severity.WARN,
                    message=f"no independent reviewer available: diff authored by "
                    f"{sorted(author_families)} and only same-family reviewer configured "
                    "— correlated blind spots possible",
                )
            )

        diff_text = ctx.diff.raw[:_MAX_DIFF_CHARS]
        raw = ""
        provider = None
        errors: list[str] = []
        for candidate in independent + same_family:
            try:
                raw = candidate.review(diff_text)
                provider = candidate
                break
            except Exception as exc:  # provider down/unfunded → try the next one
                errors.append(f"{candidate.family}: {exc}")
        if provider is None:
            result.verdict = Verdict.ERROR
            result.note = "all review providers failed: " + "; ".join(errors)
            return result
        if errors:
            result.note = "provider fallback: " + "; ".join(errors)
        for item in _parse_findings(raw):
            sev = Severity.BLOCK if item.get("severity") == "block" else Severity.WARN
            result.findings.append(
                Finding(
                    verifier=self.name,
                    severity=sev,
                    message=item["message"],
                    file=item.get("file"),
                    line=item.get("line") if isinstance(item.get("line"), int) else None,
                )
            )

        result.metrics = {
            "reviewer": provider.family,
            "independent_of_author": provider.family not in author_families,
            "findings": len(result.findings),
        }
        if any(f.severity == Severity.BLOCK for f in result.findings):
            result.verdict = Verdict.BLOCK
        elif result.findings:
            result.verdict = Verdict.WARN
        return result
