"""Feature-group resolver.

Decides which ephemeral preview environments should exist, given the set of
feature branches currently open across the two service repos. The logic is pure
(no AWS, no network) so it is fully unit-testable - see ``feature_groups.py``.
"""

from .feature_groups import (
    Branch,
    EnvService,
    PreviewEnv,
    make_slug,
    normalize_group,
    resolve,
)

__all__ = [
    "Branch",
    "EnvService",
    "PreviewEnv",
    "make_slug",
    "normalize_group",
    "resolve",
]
