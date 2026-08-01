from __future__ import annotations

from .base import REGISTRY, Verifier, register  # noqa: F401

# Import verifier modules so they self-register.
from . import deps  # noqa: F401, E402
from . import mutation  # noqa: F401, E402
from . import tautology  # noqa: F401, E402
from . import review  # noqa: F401, E402
