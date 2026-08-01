from __future__ import annotations

import time
from abc import ABC, abstractmethod

from ..models import RunContext, Verdict, VerifierResult

REGISTRY: dict[str, type["Verifier"]] = {}


def register(cls: type["Verifier"]) -> type["Verifier"]:
    REGISTRY[cls.name] = cls
    return cls


class Verifier(ABC):
    name: str = ""

    @abstractmethod
    def run(self, ctx: RunContext) -> VerifierResult: ...

    def timed_run(self, ctx: RunContext) -> VerifierResult:
        start = time.monotonic()
        try:
            result = self.run(ctx)
        except Exception as exc:  # a broken verifier must not break the gate
            result = VerifierResult(
                verifier=self.name,
                verdict=Verdict.ERROR,
                note=f"verifier crashed: {exc}",
            )
        result.duration_s = round(time.monotonic() - start, 2)
        return result
